# Data for cinco-esquinas-map.html

**Data use:** this dataset is © Ariana Sánchez Domínguez, published here
only to power the interactive map on this site. It's publicly *viewable*
because the map has to show it to work — that's not an invitation to
scrape or redistribute it. Ask before reusing it elsewhere.

## `places.json`

The dataset behind [`cinco-esquinas-map.html`](../../cinco-esquinas-map.html) —
one entry per place mentioned in *Cinco esquinas*, curated from a source CSV
that is **deliberately not published in this repo** (see below). The page
`fetch()`es this file at load time; nothing else in the map is fetched live.

This is already a reduced view of the underlying curation: the source CSV
also has `Entity`, `Place Check`, `Coor Check`, and free-text `Comments`
columns (editorial working notes) that aren't in `places.json` and aren't
needed by the map — only what's actually shown on the page (place names,
coordinates, sentences, hierarchy) is published.

Each place has:

- `name`, `lat`, `lon` — from the curated CSV.
- `mentions` — every sentence (with book + row ID) where the place is named.
- `kind` — `"area"` or `"point"`, from the CSV's `Type` column.
- `tier` — `country` / `region` / `district` / `local` / `point`. Drives both
  the zoom level at which a place appears and its default circle-fallback
  size. Hand-assigned in the build script.
- `parent` — the containing place's name (or `null` for Perú, the root).
  Broad areas hide once you zoom in far enough to see their children —
  this is what makes that work.
- `boundary` *(optional)* — real GeoJSON geometry (`Polygon`/`MultiPolygon`
  for areas, `LineString`/`MultiLineString` for streets), fetched from
  OpenStreetMap/Natural Earth. Where this is missing: an area-tier place
  falls back to an approximate circle (`radiusM`); a `local`-tier place
  with no boundary falls back to a pin, since a circle would misrepresent
  something as specific as one named street.
- `radiusM` *(area places only)* — the circle-fallback radius in meters.

## `scripts/build_places.py`

Regenerates `places.json` from scratch: parses the CSV, assigns the
tier/parent hierarchy, and fetches real boundary geometry for anything that
has it in OpenStreetMap (by relation ID, not name search — see the comments
in the script for why: street/place names collide across the metro area
often enough that a name search alone returns the wrong feature).

Requires internet access and Node.js (`npx mapshaper` is used to simplify
large polygons — no separate install needed, `npx` fetches it on demand) to
**run**. The output file it produces does not — `places.json` is a static
file, safe to commit, and that's all the published page needs.

The source CSV (`MVLL-Locations-Valid.csv`, the human-curated place
mentions with editorial columns) lives **outside this repo**, in a private
sibling folder next to it: `../arianasanchezdominguez-private-data/` (set
the `MVLL_CSV_PATH` environment variable to point elsewhere). It is not
published — only the reduced `places.json` this script produces is.

```
python Data/cinco-esquinas-map/scripts/build_places.py
```

Raw API responses are cached in `scripts/.cache/` (git-ignored) so re-runs
don't re-fetch anything already fetched — delete that folder to force a
fresh pull.

### Known gaps (by design, not a bug)

- **Barrios Altos** and **Chosica** have no boundary in OpenStreetMap at
  all — confirmed independently via both Nominatim and Overpass. They stay
  circles. A different source (e.g. Peru's official INEI boundaries) would
  be needed to fix this, and hasn't been investigated yet.
- **La Parada (mercado)**, **La Quipa**, **El Zanjón** — no confident name
  match within the search radius. They render as a pin at the curated
  coordinate instead of a circle (per the `local`-tier fallback rule).
- Perú's boundary is deliberately **not** the OSM administrative relation —
  that one includes Peru's ~370km territorial sea claim, which looks wrong
  on a map (extends visibly into the Pacific). It's swapped for a land-only
  shape from [Natural Earth](https://www.naturalearthdata.com/) (50m
  resolution), the standard source for exactly this "draw a country's
  coastline" use case.
