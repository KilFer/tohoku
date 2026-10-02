# Publicar Tohoku en GitHub (repositorio público)

Lista de comprobación preparada el 2026-10-01. Este repositorio sigue siendo el **privado de trabajo**; el público se genera a partir de él.

## Decisiones pendientes (del usuario)

- [x] **Idioma** (decidido 2026-10-02): inglés + español. El inglés es la base (`README.md`) y el español la versión accesible (`README.es.md`). Igual para toda la documentación pública (`docs/`: etapas, flujos, operación, modelo de Trilium): versión inglesa como principal y la española al lado. Estructura: sufijo `.es.md` junto a cada documento. Alcance en el código (decidido 2026-10-02): se traducen docstrings y comentarios; **no** se traducen las claves del YAML, los títulos de las notas de Trilium, los mensajes del CLI/logs/avisos ni los prompts (son identificadores o datos persistidos y la salida de las notas va en español).
- [x] **Licencia** (decidido 2026-10-02): MIT. Titular: "Fernando". `LICENSE` y metadatos de `pyproject.toml` añadidos; sección "Licencia" del README completada.
- [x] **Historial** (decidido 2026-10-02): repositorio nuevo con historial limpio (un commit inicial). Este repo privado sigue siendo el de trabajo, con todo el historial (los 124 commits llevan versiones antiguas de `CLAUDE.md` con datos personales, por eso no se reescribe). Estado de ramas comprobado ese día: `master` = lo desplegado (`841508a`), `feat/publicacion` va 1 commit por delante (fast-forward limpio) y `feat/tohoku` ya no existe. El árbol público se exporta con `git archive` excluyendo `CLAUDE.md` y `docs/superpowers/`.
- [x] **Autoría de los commits** (decidido 2026-10-02): el `noreply` de GitHub (`<id>+<usuario>@users.noreply.github.com`), no `fjbelaza@gmail.com`. Email: `290854+KilFer@users.noreply.github.com` (usuario `KilFer`). Configurarlo solo en el repo nuevo (`git config user.email` local), nunca en el global ni en este repo. En GitHub, activar "Keep my email addresses private" y "Block command line pushes that expose my email".
- [x] **`docs/superpowers/`** (decidido 2026-10-02): no se publica nada, la carpeta entera queda fuera.

## Hecho (a 2026-10-02)

- README y documentación pública en inglés (base) y español (`.es.md`), sin historia interna ni datos personales; `docs/superpowers/` y `CLAUDE.md` quedan fuera de la exportación.
- `config/destinos.example.yaml` (con marcadores en vez del id real); `config/destinos.yaml` no se exporta. `docs/operations.md` sin el id real de la lista.
- Sin referencias a fases/spec en código y tests; compatibilidad previa eliminada tras migrar producción; sin nombres ni lógica de Japón en el código (la configuración de Japón es el ejemplo de referencia); bug de `ViajeParams` para destinos que no son Japón corregido.
- `LICENSE` (MIT), metadatos de `pyproject.toml`, `.env.example`, `Dockerfile` y `docker-compose.yml` con comentarios en inglés.
- Tests: todas las URLs son sintéticas (comprobado); fixtures con identificadores de Google y claves de nombres **sintetizados** (el test `name_keys` ahora usa 37 nombres inventados que cubren acentos, CJK, puntuación, palabras genéricas, dígitos y bordes).
- Traducción de docstrings y comentarios del código al inglés, verificada con un script que comprueba que solo cambian comentarios y docstrings inertes (los de modelos pydantic, enums y la ayuda del CLI no se tocan).
- Prompts en español (decidido): documentado en el README que se adaptan por destino.

## Pendiente

### Tuyo
- [ ] **Capturas** en `docs/img/` (huecos `<!-- CAPTURA: … -->` en el README): `geo-map.png`, `lugar.png`, `comprar.png`, `recetario-tabla.png`, `recetario-cuadricula.png`, `receta.png`, `bandeja.png`. Revisa que no salgan otras notas del árbol, nombres de usuario ni URLs internas.

### A tratar con más detalle
- [ ] **Red de Docker y `TZ` configurables** (`docker-compose.yml`, `Dockerfile`, `.env.example`; hoy red externa fija `pangolin` y `Europe/Madrid`). Opción: `${DOCKER_NETWORK:-tohoku}` y `${TZ:-UTC}`; habría que añadir `DOCKER_NETWORK=pangolin` y `TZ=Europe/Madrid` al `.env` de producción. Quitar la referencia a `pangolin` del `.env.example`/README al hacerlo (los marcadores `<!-- TODO: -->` del README).
- [ ] **Exportación y verificación final**: `git archive` sin `CLAUDE.md`, `docs/superpowers/`, `docs/publicacion.md` ni `config/destinos.yaml`; `git init` + commit inicial con el noreply; `git grep -n -iE "belaza|delfos|pangolin|kamo|seo5xdpq|@gmail|/media/1tb-disk"` sin resultados; `gitleaks`; repo privado primero y luego público. Repetir la exportación para cada cambio futuro (o rama `public`).

### Extras (no bloquean)
- [ ] `CONTRIBUTING.md` breve, CI en GitHub Actions (`uv sync` + `uv run pytest`), badges y temas del repo (`karakeep`, `trilium`, `instagram`, `whisper`, `llm`, `travel`, `recipes`).

## Proceso propuesto

1. Cambios de código y configuración en `feat/publicacion` (TDD donde cambie comportamiento), integrar en `master` y desplegar (comprobar que producción sigue igual).
2. Exportar el árbol limpio a un directorio nuevo, `git init`, commit inicial, búsqueda final de datos personales y secretos.
3. Crear el repositorio en GitHub (privado primero), revisar el render del README y las capturas, y entonces hacerlo público.
4. Para publicar cambios futuros: repetir la exportación, o mantener el público como remoto de una rama `public` sin los ficheros privados.
