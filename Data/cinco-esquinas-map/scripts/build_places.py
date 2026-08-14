"""
Builds Data/cinco-esquinas-map/places.json — the dataset behind
cinco-esquinas-map.html (fetched by the page at runtime; the published site
stays fully static, nothing is called live from the browser).

Pipeline:
  1. Parse Data/MVLL-Locations-Valid.csv (the human-curated place mentions)
     and group by "Place Final" into one entry per place.
  2. Attach a hand-authored tier ("country"/"region"/"district"/"local"/
     "point") and parent for the zoom-tiered hierarchy the map uses to
     show/hide nested areas (Perú -> Lima -> districts -> streets/points).
  3. Attach real boundary geometry where it exists in OpenStreetMap, fetched
     via Nominatim BY RELATION ID, not by name search — name search is
     unreliable (e.g. "Jirón Junín" matches three unrelated streets with
     that name across the Lima metro area; "San Isidro" matches an
     unrelated village). IDs below were identified and verified by hand,
     once, during development.
  4. For streets/informal local places without a known relation ID, fall
     back to a *bounded* Nominatim search (a small box around the place's
     already-curated coordinate) plus a name-token match, which resolves
     the ambiguity problem well enough to be usable.
  5. Replace Perú's OSM admin boundary with a Natural Earth land boundary —
     OSM's admin relation for Peru includes its ~370km territorial sea
     claim, which looks wrong on a map (extends visibly into the Pacific).
  6. Simplify large polygons with mapshaper (via `npx`, no install needed)
     so the final JSON stays small enough to fetch on page load.

Requires internet access and Node.js (for `npx mapshaper`) to RUN. The
output (places.json) does not — it's a static file, safe to commit and to
fetch from the page without re-running any of this.

Usage: python build_places.py
"""

import csv
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.dirname(HERE)  # Data/
CSV_PATH = os.path.join(DATA_DIR, "MVLL-Locations-Valid.csv")
OUT_PATH = os.path.join(os.path.dirname(HERE), "cinco-esquinas-map", "places.json")
CACHE_DIR = os.path.join(HERE, ".cache")  # raw API responses, so re-runs don't re-fetch
os.makedirs(CACHE_DIR, exist_ok=True)

USER_AGENT = "LiteraryMapPrototype/0.1 (research; contact: plamctab@gmail.com)"
NOMINATIM_DELAY = 1.1  # seconds between requests — stays under Nominatim's 1 req/sec limit

NPX = "npx"  # on Windows this resolves via PATH/npx.cmd automatically


# ---------------------------------------------------------------------------
# Step 1-2: parse the curated CSV, assign tier + parent hierarchy
# ---------------------------------------------------------------------------

# tier -> default area radius in meters, used only for the *circle fallback*
# (places that end up with no real boundary geometry at all).
TIER_RADIUS = {"country": 90000, "region": 6000, "district": 1200, "local": 350}

# name -> (tier, parent, radius_override_or_None)
# Hand-assigned from the novel's own text where it names a containing
# district (e.g. Hotel Mogollón, Cinco Esquinas -> Barrios Altos), and to
# the nearest sensible container otherwise. See CLAUDE session history /
# README.md in this folder for the full reasoning per place.
PLACES_META = {
    "Perú": ("country", None, None),

    "Lima": ("region", "Perú", 14000),
    "Chosica": ("region", "Perú", None),
    "Arequipa": ("region", "Perú", None),
    "Cusco": ("region", "Perú", None),
    "Ayacucho": ("region", "Perú", None),
    "Huancavelica": ("region", "Perú", None),
    "Ica": ("region", "Perú", None),
    "Puno": ("region", "Perú", None),

    "Barrios Altos": ("district", "Lima", None),
    "Surquillo": ("district", "Lima", None),
    "San Isidro": ("district", "Lima", None),
    "Miraflores": ("district", "Lima", None),
    "Callao": ("district", "Lima", 1800),
    "Chorrillos": ("district", "Lima", None),
    "Rímac": ("district", "Lima", None),
    "Breña": ("district", "Lima", None),

    "Cinco Esquinas": ("local", "Barrios Altos", 500),
    "Jirón Junín": ("local", "Barrios Altos", None),
    "Avenida Abancay": ("local", "Barrios Altos", None),
    "Jirón Teniente Arancibia": ("local", "Barrios Altos", None),
    "Jirón Huallaga": ("local", "Barrios Altos", None),
    "Calle Dante": ("local", "Surquillo", None),
    "Calle Irribarren": ("local", "Surquillo", None),
    "Cantagallo": ("local", "Rímac", 700),
    "La Perla": ("local", "Callao", 700),
    "Avenida Grau": ("local", "Lima", None),
    "El Zanjón": ("local", "Lima", None),
    "Avenida Tacna": ("local", "Lima", None),
    "Avenida Arica": ("local", "Lima", None),
    "Avenida España": ("local", "Lima", None),
    "Avenida Argentina": ("local", "Lima", None),
    "Jirón Ocoña": ("local", "Lima", None),
    "La Parada (mercado)": ("local", "Lima", None),
    "La Rinconada": ("local", "Lima", 500),
    "La Quipa": ("local", "Perú", 500),
    "La Honda": ("local", "Perú", 500),

    "Hotel Mogollón": ("point", "Barrios Altos", None),
    "Monasterio Nuestra Señora del Carmen": ("point", "Barrios Altos", None),
    "Plaza Italia": ("point", "Barrios Altos", None),
    "Los Siete Pescados Capitales": ("point", "Miraflores", None),
    "Larcomar": ("point", "Miraflores", None),
    "Teatro Alfonso XIII del Callao": ("point", "Callao", None),
    "Machu Picchu": ("point", "Cusco", None),
    "Club de la Banca": ("point", "Lima", None),
    "Hotel Sheraton": ("point", "Lima", None),
    "María Parado de Bellido": ("point", "Lima", None),
    "Plaza San Martín": ("point", "Lima", None),
    "Pontificia Universidad Católica del Perú": ("point", "Lima", None),
}


def parse_csv():
    places, order = {}, []
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("Place Final") or "").strip()
            coords_raw = (row.get("Coordinates Final") or "").strip()
            m = re.match(r"^\{\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\}$", coords_raw)
            if not m:
                continue
            lat, lon = float(m.group(1)), float(m.group(2))
            sentence = re.sub(r"\s+", " ", (row.get("Sentence") or "").strip())

            if name not in places:
                if name not in PLACES_META:
                    raise SystemExit(f"No tier/parent assignment for place: {name!r} — add it to PLACES_META")
                tier, parent, radius_override = PLACES_META[name]
                entry = {
                    "name": name, "lat": lat, "lon": lon,
                    "kind": "point" if tier == "point" else "area",
                    "tier": tier, "parent": parent, "mentions": [],
                }
                if entry["kind"] == "area":
                    entry["radiusM"] = radius_override or TIER_RADIUS[tier]
                places[name] = entry
                order.append(name)

            places[name]["mentions"].append({
                "id": (row.get("ID") or "").strip(),
                "book": (row.get("Book") or "").strip(),
                "sentence": sentence,
            })
    return [places[n] for n in order]


# ---------------------------------------------------------------------------
# Nominatim helpers (shared by admin-boundary and local-boundary steps)
# ---------------------------------------------------------------------------

def nominatim_get(path, params, cache_key):
    cache_path = os.path.join(CACHE_DIR, cache_key + ".json")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    url = f"https://nominatim.openstreetmap.org/{path}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    time.sleep(NOMINATIM_DELAY)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def simplify_geometry(geometry, pct):
    """Run one GeoJSON geometry through mapshaper -simplify and return the
    simplified geometry. Requires Node/npx; falls back to the raw geometry
    (with a warning) if mapshaper isn't available."""
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geometry}]}
    raw_path = os.path.join(CACHE_DIR, "_simplify_in.geojson")
    out_path = os.path.join(CACHE_DIR, "_simplify_out.geojson")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(fc, f)
    try:
        subprocess.run([NPX, "--yes", "mapshaper", raw_path, "-simplify", pct, "-o", out_path, "force"],
                        check=True, capture_output=True, text=True, shell=(os.name == "nt"))
    except Exception as e:
        print(f"  ! mapshaper unavailable ({e}); keeping unsimplified geometry", file=sys.stderr)
        return geometry
    with open(out_path, encoding="utf-8") as f:
        result = json.load(f)
    if result.get("type") == "FeatureCollection":
        return result["features"][0]["geometry"]
    if result.get("type") == "GeometryCollection":
        return result["geometries"][0]
    return result


# ---------------------------------------------------------------------------
# Step 3: administrative boundaries (country / Lima / districts / region
# cities), fetched by known OSM relation ID — see comments for why each ID.
# ---------------------------------------------------------------------------

# name -> (relation id, mapshaper simplify %)
ADMIN_BOUNDARY_IDS = {
    "Perú": ("288247", "2%"),
    # Lima: relation 1944670 is the PROVINCE ("Lima, Lima Metropolitana,
    # Lima, Perú", place_rank 12) — not relation 1944659, the broader
    # DEPARTMENT (place_rank 8), which also includes places like Huaral/
    # Cañete that the novel doesn't mean by "Lima".
    "Lima": ("1944670", "6%"),
    "San Isidro": ("1944812", "20%"),
    "Miraflores": ("1944770", "20%"),
    "Surquillo": ("1944852", "20%"),
    "Callao": ("1944699", "20%"),  # city-level (rank 16), matching the other districts' resolution
    "Chorrillos": ("1944714", "20%"),
    "Rímac": ("1944796", "20%"),
    "Breña": ("1944693", "20%"),
    # NOTE: "Barrios Altos" deliberately has no entry — Nominatim's only
    # match for that name is an unrelated small "Urbanización Barrios
    # Altos" (rank 20), confirmed via a second, independent lookup on
    # Overpass too (the only Overpass hit was a supermarket whose address
    # happens to say "Barrios Altos"). It's not mapped as a shape in OSM at
    # all — the historic neighbourhood the novel means isn't an official
    # administrative unit. Keeps the circle fallback.
    # NOTE: "Chosica" also has no entry — no OSM admin relation exists for
    # it either; it's a locality inside the Lurigancho district, not its
    # own administrative unit.
    "Arequipa": ("1887794", "10%"),      # province-level, consistent with Lima's resolution
    "Ayacucho": ("1930922", "10%"),      # district-level — no province-level "Ayacucho" entity exists separately
    "Cusco": ("1923702", "10%"),
    "Huancavelica": ("1933556", "10%"),
    "Ica": ("1899015", "10%"),
    "Puno": ("1913490", "10%"),
}


def fetch_admin_boundaries():
    ids = ",".join(f"R{v[0]}" for v in ADMIN_BOUNDARY_IDS.values())
    results = nominatim_get("lookup", {"osm_ids": ids, "format": "jsonv2", "polygon_geojson": 1}, "admin_lookup")
    by_id = {str(r["osm_id"]): r for r in results}

    out = {}
    for name, (osm_id, pct) in ADMIN_BOUNDARY_IDS.items():
        if osm_id not in by_id:
            print(f"  ! {name}: relation {osm_id} not found in lookup response, skipping", file=sys.stderr)
            continue
        geom = simplify_geometry(by_id[osm_id]["geojson"], pct)
        out[name] = geom
        print(f"  {name}: relation {osm_id} -> {geom['type']}", file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Step 4: streets / informal local places, via bounded search + name match
# ---------------------------------------------------------------------------

STOPWORDS = {"la", "el", "los", "las", "de", "del", "avenida", "jiron", "jirón", "calle", "mercado"}


def _normalize(s):
    s = s.lower()
    for a, b in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")]:
        s = s.replace(a, b)
    return s


def _tokens(name):
    return {_normalize(t) for t in re.findall(r"[A-Za-zÀ-ÿ]+", name) if _normalize(t) not in STOPWORDS}


def _first_coord(geom):
    c = geom["coordinates"]
    while isinstance(c, list) and c and not isinstance(c[0], (int, float)):
        c = c[0]
    return c


def _dist(lonlat, lat, lon):
    return math.hypot(lonlat[0] - lon, lonlat[1] - lat)


def fetch_local_boundary(place, box_deg=0.008):
    """Bounded name search around the place's own curated coordinate — the
    box makes name collisions across the metro area a non-issue (a search
    for a common street name only sees candidates within ~1km of our point).
    Groups same-named segments into one Multi*, picks the nearest group if
    several distinct names matched, and rejects candidates that don't share
    at least one significant word with the place name (filters out
    unrelated nearby features Nominatim returns as loose fuzzy matches)."""
    lat, lon = place["lat"], place["lon"]
    viewbox = f"{lon-box_deg},{lat+box_deg},{lon+box_deg},{lat-box_deg}"
    cache_key = "local_" + re.sub(r"[^a-zA-Z0-9]", "_", place["name"])
    candidates = nominatim_get("search", {
        "q": place["name"], "format": "jsonv2", "polygon_geojson": 1,
        "limit": 5, "viewbox": viewbox, "bounded": 1,
    }, cache_key)

    want = _tokens(place["name"])
    accepted = []
    for c in candidates:
        gj = c.get("geojson")
        if not gj or gj["type"] == "Point":
            continue
        cname = c.get("name") or (c.get("display_name") or "").split(",")[0]
        if want & _tokens(cname):
            accepted.append((cname, gj))
    if not accepted:
        return None

    groups = {}
    for cname, gj in accepted:
        groups.setdefault(cname, []).append(gj)
    best_name, best_geoms, best_dist = None, None, None
    for cname, geoms in groups.items():
        d = min(_dist(_first_coord(g), lat, lon) for g in geoms)
        if best_dist is None or d < best_dist:
            best_name, best_geoms, best_dist = cname, geoms, d

    types = {g["type"] for g in best_geoms}
    if types <= {"Polygon", "MultiPolygon"}:
        coords = []
        for g in best_geoms:
            coords.extend(g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]])
        return {"type": "MultiPolygon", "coordinates": coords} if len(coords) > 1 else {"type": "Polygon", "coordinates": coords[0]}
    if types <= {"LineString", "MultiLineString"}:
        coords = []
        for g in best_geoms:
            coords.extend(g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]])
        return {"type": "MultiLineString", "coordinates": coords}
    return None  # mixed/unsupported geometry types — skip, keep fallback


# ---------------------------------------------------------------------------
# Step 5: Perú's boundary — swap OSM's admin relation (includes ~370km of
# territorial sea) for a land-only shape from Natural Earth.
# ---------------------------------------------------------------------------

NATURAL_EARTH_50M_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"


def fetch_peru_land_boundary():
    cache_path = os.path.join(CACHE_DIR, "ne_countries_50m.geojson")
    if not os.path.exists(cache_path):
        req = urllib.request.Request(NATURAL_EARTH_50M_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=40) as resp:
            raw = resp.read()
        with open(cache_path, "wb") as f:
            f.write(raw)
    with open(cache_path, encoding="utf-8-sig") as f:
        data = json.load(f)
    for feat in data["features"]:
        if feat["properties"].get("ADM0_A3") == "PER":
            return feat["geometry"]
    raise SystemExit("Peru not found in Natural Earth countries file")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("1. Parsing CSV + assigning hierarchy...", file=sys.stderr)
    places = parse_csv()
    print(f"   {len(places)} unique places", file=sys.stderr)

    print("2. Fetching administrative boundaries (country/Lima/districts/regions)...", file=sys.stderr)
    admin = fetch_admin_boundaries()

    print("3. Fetching street/local-place boundaries (bounded search)...", file=sys.stderr)
    local_boundaries = {}
    for p in places:
        if p["kind"] == "area" and p["tier"] == "local" and p["name"] not in admin:
            geom = fetch_local_boundary(p)
            if geom:
                local_boundaries[p["name"]] = geom
                print(f"   {p['name']}: {geom['type']}", file=sys.stderr)
            else:
                print(f"   {p['name']}: no usable match, keeps pin fallback", file=sys.stderr)

    print("4. Replacing Perú's boundary with a land-only shape...", file=sys.stderr)
    peru_land = fetch_peru_land_boundary()

    boundaries = {**admin, **local_boundaries, "Perú": peru_land}
    for p in places:
        if p["name"] in boundaries:
            p["boundary"] = boundaries[p["name"]]

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(places, f, ensure_ascii=False)

    with_boundary = sum(1 for p in places if p["kind"] == "area" and "boundary" in p)
    total_areas = sum(1 for p in places if p["kind"] == "area")
    print(f"\nWrote {OUT_PATH}", file=sys.stderr)
    print(f"{with_boundary}/{total_areas} area places have real boundary geometry", file=sys.stderr)
    print("Still circle/pin fallback:", [p["name"] for p in places if p["kind"] == "area" and "boundary" not in p], file=sys.stderr)


if __name__ == "__main__":
    main()
