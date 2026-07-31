# Tu sitio personal

Un sitio estático minimalista, estilo "cuaderno de campo", para mostrar
tus proyectos y pasiones — inspirado en la estructura de phileasdg.github.io
pero con un diseño propio (tarjetas tipo ficha de archivo con sello y fecha).

## Archivos

- `index.html` — página principal, con la lista de entradas ("el archivo")
- `proyecto-ejemplo.html` — plantilla para la página de un proyecto individual
- `styles.css` — todo el diseño (colores, tipografía, layout)
- `assets/` — carpeta para tus imágenes

## Cómo personalizarlo

1. **Tu información**: en `index.html`, reemplaza "Tu Nombre", la frase de
   presentación (`tagline`) y los enlaces de `site-links` (GitHub, correo, etc.).
2. **Tus entradas**: cada proyecto es un bloque `<li class="entry">…</li>`.
   Copia uno nuevo por cada proyecto o pasión que quieras añadir, y ajusta:
   - `stamp`: fecha o número (ej. `2026 · 02`)
   - el título y su enlace (crea una copia de `proyecto-ejemplo.html` con
     un nombre de archivo distinto, ej. `mi-proyecto.html`)
   - la descripción de una línea
   - los `tags`
3. **Páginas de proyecto**: duplica `proyecto-ejemplo.html` por cada entrada,
   renómbralo, y escribe el contenido. Puedes añadir imágenes dentro de `assets/`.
4. **Colores y tipografía**: todo está centralizado como variables al inicio
   de `styles.css` (bloque `:root`). Cambia `--paper`, `--accent`, `--stamp`
   etc. si quieres otra paleta.

## Cómo publicarlo en GitHub Pages

1. Crea un repositorio en GitHub llamado `tu-usuario.github.io`
   (sustituye `tu-usuario` por tu nombre de usuario real de GitHub).
2. Sube estos archivos a la raíz del repositorio.
3. Ve a **Settings → Pages** en el repositorio y confirma que la fuente
   sea la rama `main` (o `master`), carpeta raíz `/`.
4. En un par de minutos tu sitio estará disponible en
   `https://tu-usuario.github.io`.

Si prefieres que el sitio viva en una subcarpeta de un repo existente en
vez de en `tu-usuario.github.io`, funciona igual — solo cambia la URL final.
