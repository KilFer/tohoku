# Publicar Tohoku en GitHub (repositorio público)

Lista de comprobación preparada el 2026-10-01. Este repositorio sigue siendo el **privado de trabajo**; el público se genera a partir de él.

## Decisiones pendientes (del usuario)

- [ ] **Idioma** del README y de la documentación pública: español (como ahora), inglés o los dos (p. ej. `README.md` en inglés + `README.es.md`).
- [ ] **Licencia**: MIT, GPL-3.0 u otra. Añadir el fichero `LICENSE` y completar la sección "Licencia" del README.
- [ ] **Historial**: recomendado, un repositorio nuevo con historial limpio (un commit inicial). La alternativa es reescribir este historial (`git filter-repo`), más arriesgada: los 124 commits llevan versiones antiguas de `CLAUDE.md` con datos personales.
- [ ] **Autoría de los commits**: email real o el `noreply` de GitHub.
- [ ] Qué se publica de `docs/superpowers/` (specs y planes): nada (recomendado), solo las specs (limpias) o todo.

## README

Borrador nuevo ya escrito en `README.md` (rama `feat/publicacion`). Falta:

- [ ] **Capturas** (el usuario las añade) en `docs/img/`. Huecos marcados en el README con `<!-- CAPTURA: … -->`:
  - `geo-map.png`: Geo Map de un viaje con lugares.
  - `lugar.png`: nota de un lugar con sus fuentes.
  - `comprar.png`: sección "Comprar y comer".
  - `recetario-tabla.png`: Recetario en vista Tabla.
  - `recetario-cuadricula.png`: Recetario en vista Cuadrícula con portadas.
  - `receta.png`: nota de una receta.
  - `bandeja.png`: Bandeja de revisión.
  - Revisar que no salgan datos personales (otras notas del árbol de Trilium, nombres de usuario, URLs internas).
- [ ] Sección "Licencia" (cuando se decida).
- [ ] Traducción, si se decide inglés.
- [ ] Revisar los marcadores `<!-- PENDIENTE: … -->` del README (se resuelven con los cambios de abajo).

## Cambios de código y configuración antes de publicar

- [ ] **`config/destinos.example.yaml`** con listas de ejemplo (`<id-lista-karakeep>`), y `config/destinos.yaml` fuera del repositorio público (o en `.gitignore`). Hoy lleva el id real de la lista "Japón". Revisar que el Dockerfile (`COPY config`) y el arranque funcionen sin el fichero real (mensaje claro si falta).
- [ ] **Red de Docker configurable** en `docker-compose.yml`: hoy es la red externa fija `pangolin`. Opción: `name: ${DOCKER_NETWORK:-tohoku}` o un `docker-compose.override.yml` documentado.
- [ ] **`TZ`** del Dockerfile y del compose (`Europe/Madrid`) como variable con valor por defecto.
- [ ] **`.env.example`**: quitar la referencia a la red "pangolin"; revisar que todos los valores sean de ejemplo.
- [ ] **`docs/operations.md`**: sustituir el id real de la lista (`seo5xdpq…`) por un marcador; revisar rutas del servidor.
- [ ] **Tests**: ~40 URLs reales de Reels guardados (`test_instagram_export.py`, `test_downloaders.py`, `test_sources.py`…) y `eval/cases.yaml` → URLs de ejemplo con el mismo formato. Revisar `tests/fixtures/` (resultados de etapa reales: textos de fuentes de terceros).
- [ ] **`CLAUDE.md`**: no se publica (diario de operación con servidor, dominio y topic de ntfy, ids, presupuestos). Si se quiere un `CLAUDE.md`/`AGENTS.md` público, uno nuevo solo con reglas de desarrollo.
- [ ] **`docs/superpowers/`**: según la decisión de arriba. Contienen el email en un `git config`, rutas del servidor y detalles de la instalación.
- [ ] Búsqueda final en el árbol que se va a publicar: `git grep -n -iE "belaza|delfos|pangolin|kamo|seo5xdpq|@gmail|/media/1tb-disk"` sin resultados.
- [ ] Secretos: comprobado el 2026-10-01 que `.env`, `secrets/` y `data/` nunca se han subido y que no hay claves en el historial. Repetir la comprobación en el árbol final (p. ej. con `gitleaks`).

## Extras recomendables (no bloquean)

- [ ] `CONTRIBUTING.md` breve (cómo correr los tests, TDD, idioma) o una sección en el README.
- [ ] CI en GitHub Actions: `uv sync` + `uv run pytest` (los unitarios no usan red).
- [ ] Badges (licencia, tests) en el README.
- [ ] Temas del repositorio en GitHub: `karakeep`, `trilium`, `instagram`, `whisper`, `llm`, `travel`, `recipes`.

## Proceso propuesto

1. Hacer los cambios de código y configuración en `feat/publicacion` (TDD donde cambie comportamiento), integrar en `master` y desplegar (comprobar que producción sigue igual).
2. Exportar el árbol limpio (`git archive master` sin `CLAUDE.md`, `docs/superpowers/` ni ficheros privados) a un directorio nuevo, `git init`, commit inicial, búsqueda final de datos personales.
3. Crear el repositorio en GitHub (privado primero), revisar el render del README y las capturas, y entonces hacerlo público.
4. Para publicar cambios futuros: repetir la exportación, o mantener el público como remoto de una rama `public` sin los ficheros privados.
