# Atlas de tablas

Visor estático en español para tablas LaTeX con bibliografía BibTeX. Incluye dos tablas de ejemplo sobre coorbitales y cinco referencias bibliográficas. Los valores de la tabla de observables son simulados.

## Puesta en marcha

En la carpeta `proyecto`, ejecuta los comandos con Python 3.10 o posterior.

```sh
python tools/build_manifest.py
python -m http.server 8000 --bind 127.0.0.1
```

Abre [localhost:8000](http://localhost:8000/). En Windows puedes sustituir `python` por `py` si usas el lanzador. El servidor sirve archivos estáticos y puedes alojar la misma carpeta en cualquier alojamiento estático. Algunos navegadores bloquean `fetch` y los módulos JavaScript bajo `file://` porque los archivos locales no comparten un origen HTTP válido. KaTeX 0.19.1 y sus fuentes se incluyen en `vendor/katex/`, con su licencia. [Documentación de KaTeX](https://katex.org/docs/browser.html)

## Añadir o editar contenido

1. Guarda un archivo `.tex` por tabla en `data/tablas/` y uno o más `.bib` en `data/bib/`. Puedes organizarlos en subcarpetas. Usa UTF-8 sin BOM.
2. Añade `\caption{Título}` y, si quieres filtrar por etiqueta o enlazar desde otra tabla, `\label{tab:clave}`. Sin título, el visor usa el nombre del archivo. Usa las claves de los `.bib` dentro de `\cite{clave}` y sus variantes.
3. Ejecuta `python tools/build_manifest.py` para actualizar `data/manifest.json`. Luego ejecuta `python tools/check_integrity.py` y recarga la página.

El buscador consulta títulos, etiquetas, contenido y citas, sin distinguir mayúsculas o tildes. Los filtros de etiqueta y clave pueden combinarse. Al abrir una cita se muestran los campos de la entrada, su BibTeX original y los enlaces disponibles. Los botones de la tabla copian la fuente o el CSV al portapapeles y descargan el `.tex`.

## Verificación y correcciones

```sh
python tools/check_integrity.py
python tools/fix_issues.py --dry-run
python tools/fix_issues.py
```

- Los tres scripts aceptan `--help` y `--root`. El código de salida es `0` con verificación correcta y `1` si hay errores. Las advertencias por sí solas permiten el código `0`.
- El verificador revisa LaTeX, BibTeX, citas, etiquetas, manifiesto, rutas estáticas, HTML y UTF-8. Si Node está instalado, ejecuta `node --check` sobre el JavaScript del visor. Cada ejecución escribe `tools/report.md` y muestra el diagnóstico en consola. El puntaje parte en 100 y descuenta 10 puntos por error y 2 por advertencia.
- El corrector convierte codificaciones identificadas por BOM, normaliza saltos y líneas en blanco donde es seguro, escapa caracteres inequívocos en contexto de texto, retira entradas BibTeX idénticas y regenera el manifiesto. Conserva los archivos originales en `backup/<ejecución>/` con sus rutas relativas. Si crea un archivo, registra su ruta en `archivos-nuevos.txt` de la copia. Para revertir, repón los originales y retira los archivos que se generaron en esa ejecución.
- `--dry-run` muestra en consola los cambios propuestos y los problemas del estado actual. Las claves que faltan, los duplicados con valores distintos y las filas ambiguas se informan con su línea y una sugerencia. Un `&` fuera de un grupo de texto se interpreta como separador. Un `%` sin escape abre un comentario, y solo se corrige automáticamente si el porcentaje está junto a un delimitador y escaparlo resuelve un error de su fila.

Pruebas unitarias incluidas, sin dependencias de Python. Usa Node 22 o posterior para las pruebas JavaScript.

```sh
python -m unittest discover -s tests
node --test tests/parsers.test.mjs
```

Para la prueba de humo opcional, instala Playwright en `proyecto/` y su Chromium. El verificador inicia y cierra su propio servidor local, comprueba las tablas, las fórmulas y la apertura de cada enlace de referencia, y captura los errores del navegador. `ATLAS_CHROMIUM` permite indicar la ruta a un binario Chromium existente.

```sh
npm install --no-save --package-lock=false playwright
npx playwright install chromium
python tools/check_integrity.py --smoke
```

## Alcance del parser

- Admite `tabular`, `tabular*` y `longtable`, dentro o fuera de `table`. Reconoce columnas `l`, `c`, `r`, `p{}`, `m{}`, `b{}`, repetición `*{n}{…}`, líneas verticales y celdas combinadas con `\multicolumn` y `\multirow` de extensión positiva. En `longtable` muestra una vez la primera cabecera y el último pie disponibles. Para `tabular` deduce la cabecera a partir de la primera regla intermedia o de la primera fila.
- Usa KaTeX para `$…$`, `$$…$$`, `\(…\)` y `\[…\]`. Los anchos con unidades usuales y proporciones de `\textwidth`, `\linewidth` o `\columnwidth` se traducen a CSS. `\cline` y `\cmidrule` se representan como líneas de ancho completo.
- LaTeX se interpreta como un subconjunto. Los entornos anidados en una celda, los tipos de columna definidos por el usuario, las macros personalizadas y el diseño de páginas de TeX requieren adaptar la fuente. Un fallo estructural muestra el diagnóstico y el código original. Las citas ausentes se marcan en rojo y la tabla sigue visible.
- BibTeX admite grupos, valores entre comillas, concatenación con `#` y macros `@string` definidas antes de usarse en el mismo archivo. Las claves distinguen mayúsculas. Usa `author`, `title` y `year` en cada entrada. Las reglas completas de BibLaTeX, como la herencia `crossref`, quedan fuera del parser.
- El CSV coloca el contenido de cada celda combinada en su posición superior izquierda y deja vacíos los espacios cubiertos. Las fórmulas se copian como texto TeX sin delimitadores y las citas como se leen en el visor.
