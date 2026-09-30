# Tohoku (antes japan-reader): multidestino — Diseño

- **Fecha:** 2026-09-30
- **Estado:** Borrador (pendiente de revisión)
- **Autor:** Fernando + Claude
- **Parte de:** `2026-09-28-japan-reader-design.md` (sigue siendo la autoridad para todo lo que este documento no cambia)

## 1. Propósito

Pasar de un lector centrado en Japón a un lector de contenido corto **con varios destinos configurables**. Cada destino tiene su propio objetivo, su propia estructura de notas en Trilium y su propio flujo de extracción.

Ejemplos que guían el diseño:

- **Japón:** lo de hoy, sin cambios visibles.
- **Nueva Zelanda:** el mismo flujo que Japón con otra raíz, otro país y otro contexto.
- **Recetas:** un flujo distinto: ingredientes y pasos, sin geocodificar, en una colección con vista Tabla.

### Conceptos

- **Flujo (tipo de flujo):** código. Define el esquema de extracción, las etapas propias, la deduplicación, el render de la nota y la estructura en Trilium. Hay dos: `viaje` y `receta`.
- **Destino:** configuración. Es una instancia de un flujo con sus parámetros: nota raíz, país, prompt de contexto, categorías, vista… Japón y Nueva Zelanda son dos destinos del flujo `viaje`.

### Criterios de éxito

1. Añadir un destino de un flujo existente (Nueva Zelanda) requiere **solo configuración**: YAML, un fichero de contexto para el prompt y marcar la raíz en Trilium. No se toca código.
2. Añadir un flujo nuevo (Recetas) requiere un **módulo nuevo y acotado**, sin tocar el pipeline común.
3. Japón produce **exactamente lo mismo** que antes del cambio. No se migra ninguna nota de Trilium.
4. Con la cuota de Places agotada, la cola sigue avanzando con todo lo que no necesita Places.
5. Los datos intermedios no crecen sin límite.

### Fuera de alcance

- Varios destinos para un mismo enlace: un job = un destino.
- Un flujo genérico declarativo ("ficha" con campos en YAML). Puede añadirse más adelante como un flujo más.
- Presupuestos o cuotas por destino: siguen siendo globales.

## 2. Configuración: `config/destinos.yaml`

Fichero versionado, montado en el contenedor en `/config` (ruta configurable con `DESTINOS_FILE`). Los secretos siguen en `.env`. `KARAKEEP_LIST_ID` y `TRILIUM_ROOT_LABEL` desaparecen de `.env`: las listas y las raíces pasan al YAML.

```yaml
clasificador:
  modelo: <modelo barato y rápido>
  modo: json_schema                      # json_schema | etiqueta | <adaptador específico>
  confianza_minima: 0.5                  # por debajo → ninguno (descartado)
  margen_revision: 0.15                  # 2.º destino a menos de esto → clasificacion-dudosa

limpieza:
  retencion_dias: 30                     # JSON de etapas; 0 = borrar al publicar

listas:                                  # lista de Karakeep → destinos candidatos
  seo5xdpquppqfy4hmzzeekfh: [japon]
  # <id-inbox>: [japon, nueva_zelanda, recetas]

destinos:
  japon:
    flujo: viaje
    raiz: jrRoot
    descripcion: "Viaje a Japón: lugares, comida, compras y cultura de Japón"
    contexto: prompts/japon.md
    pais: JP
    palabras_genericas: [japan, japon]   # entran en #jrNombreNorm: no cambiar en destinos existentes
    categorias_lugar: [templo, santuario, comida, cafe, bar, tienda, mercado, mirador,
                       barrio, museo, parque, onsen, alojamiento, transporte, otro]
    categorias_cosa: {souvenirs: Souvenirs, comida: Comida, cadenas: Cadenas,
                      cosmetica: Cosmética, otros: Otros}
    alias_ciudad: {...}                  # hoy CITY_ALIASES en geo.py
  recetas:
    flujo: receta
    raiz: jrRootRecetas
    descripcion: "Recetas de cocina: cómo preparar un plato paso a paso"
    contexto: prompts/recetas.md
    vista: table                         # table | grid | list
    atributos: {tipo_plato: text, cocina: text, tiempo_min: number, raciones: number,
                dificultad: text, probada: boolean, valoracion: number}
```

- Se valida con Pydantic al arrancar. Cada flujo define el modelo de sus parámetros (`ViajeParams`, `RecetaParams`), así que un destino se valida contra su flujo.
- Iconos, títulos de sección y parámetros que hoy son constantes toman como **valor por defecto** el actual. Solo hace falta escribirlos en el YAML para cambiarlos.
- Los prompts **base** de cada flujo (`viaje.md`, `receta.md`) siguen en el paquete. El `contexto` de cada destino se inserta en ellos.
- **Preflight** (`ConfigError` y el servicio no arranca):
  - YAML inválido o flujo desconocido;
  - lista que apunta a un destino inexistente;
  - fichero de contexto ausente;
  - raíz del destino no encontrada o estructura incompleta en Trilium;
  - modelo de extracción sin salida estructurada o, en `viaje`, sin imágenes.
  - Al modelo del clasificador **no** se le exige salida estructurada (depende de `modo`).

## 3. Enrutado

1. **`ingest`** recorre todas las listas del YAML. Un bookmark ya conocido se ignora, como hoy. Al crear el job se guardan sus `candidates` (los destinos de la lista). Si un bookmark está en dos listas, se unen los candidatos.
2. **`classify`** (etapa común nueva, después de `transcribe`):
   - **Un solo candidato:** sin llamada al LLM, `destination = candidato` y coste 0.
   - **Varios candidatos:** una llamada solo de texto (caption, hashtags, transcripción y la `descripcion` de cada candidato). Devuelve el destino (o `ninguno`), su confianza y la alternativa con la suya. Si no hay texto útil (sin caption ni transcripción), se añaden 2 fotogramas.
   - Confianza < `confianza_minima` o `ninguno` → resultado `DESCARTADO`.
   - Si la alternativa está a menos de `margen_revision` → se publica en el mejor destino con el motivo `clasificacion-dudosa`, que entra en la Bandeja de ese destino.
3. **Relevancia dentro del destino:** sigue en `extract` (`relacionado_destino`, `confianza_destino`, los antiguos `*_japon`). Así una lista de un solo destino conserva el filtro "esto no es de Japón".
4. **Forzar destino:** `reprocess --destino <d> <id>` salta el clasificador y borra los resultados desde `classify`.

### Clasificador: modos de salida

El clasificador tiene su propia interfaz (`Classifier.classify(texto, candidatos) -> Classification`) con implementaciones intercambiables según `modo`:

- `json_schema`: `response_format` con esquema, igual que `extract`.
- `etiqueta`: se pide solo el nombre del destino (o `ninguno`) y se analiza el texto. La confianza es fija o sale de logprobs si el modelo los da.
- **Adaptadores específicos** para modelos con un formato de respuesta estructurada propio (p. ej. JEV).

**Punto abierto:** la configuración del clasificador se revisará con el modelo concreto cuando se elija. Se espera tener que ajustar el modo o añadir un adaptador.

Si la respuesta no se entiende (destino inventado, formato roto), se reintenta una vez con la corrección. Si sigue fallando, es un fallo temporal (backoff) y, agotados los reintentos, `jr:error`. Nunca se adivina un destino.

## 4. Pipeline

```
común:  fetch → transcribe → classify
flujo:  viaje   = extract → geocode → resolve → publish
        receta  = extract → cover → resolve → publish
final:  mark
```

- `Pipeline` ejecuta el tramo común y después `FlowRegistry[dest.flujo].stages(dest)`. Las etapas de flujo reciben el `Destination` (los parámetros ya validados).
- La persistencia por etapa sigue igual: cada resultado se guarda en `stage_results` al terminar y, al reanudar, se salta lo ya hecho.

### Cuotas por clave (la cola no se para)

- Cada etapa declara la cuota que consume: `geocode` → `places_calls`; `classify`, `extract` y `publish` → `openrouter_usd`.
- `QuotaExceeded` lleva su clave. El job afectado se aparca hasta el siguiente reinicio de cuota, sin gastar un intento. Durante **esa pasada**, a cualquier otro job que llegue a una etapa con esa clave se le aparca antes de ejecutarla, sin llamar a la API. Todo lo demás sigue.
- El aviso por ntfy se manda una vez al día por clave, como hoy.

## 5. Estado (`state.db`)

- `jobs` gana `candidates TEXT` (JSON) y `destination TEXT`. Migración idempotente al arrancar (`ALTER TABLE … ADD COLUMN` si falta). A los jobs existentes se les asigna `candidates=["japon"]` y `destination="japon"`.
- `stage_results` y `published`: sin cambios de esquema.

### Limpieza en dos niveles

1. **Al terminar un job con éxito** (cualquier resultado distinto de `ERROR`): se borra su directorio `data/jobs/<id>/` (audio, fotogramas e imágenes; la portada ya se ha subido a Trilium) y su resultado de `fetch`, que apunta a esos ficheros. Si se reprocesa, `fetch` vuelve a descargar sin coste.
2. **Tras `retencion_dias`:** se purgan los resultados de etapa del job y quedan el registro base de `jobs` y `published`, que hacen falta para la Bandeja y para el reprocesado idempotente. La purga se ejecuta una vez por pasada del servicio.
   - Un reprocesado de un job purgado rehace las etapas que falten, porque el pipeline ya ejecuta cualquier etapa sin resultado guardado.
   - `retencion_dias: 0` borra todo lo intermedio al publicar.

Los jobs en `ERROR` conservan todo para poder diagnosticarlos.

## 6. Flujos

### 6.1 Interfaz

```python
class Flow(Protocol):
    name: str
    params_model: type[BaseModel]
    def stages(self, dest: Destination) -> list[Stage]
    def init_trilium(self, dest: Destination) -> None
    def check(self, dest: Destination) -> None
```

Utilidades comunes que se extraen de `publish`/`notes` y comparten los flujos:
- llamada al LLM con reintento de esquema;
- `upsert_labels`/`sync_labels`;
- "Mis notas";
- adjunto `japan-reader.json`;
- clonado y sincronización de la Bandeja;
- `#jrItem` idempotente;
- `SourceEntry`.

### 6.2 Flujo `viaje` (el código actual, generalizado)

- **`extract`:**
  - prompt = `viaje.md` más el `contexto` del destino;
  - las categorías de lugar y de cosa salen del YAML: el esquema JSON se genera con esos `enum` y la validación usa los mismos valores;
  - `relacionado_japon` y `confianza_japon` pasan a `relacionado_destino` y `confianza_destino`, aceptando los nombres antiguos como alias al leer (`stage_results` existentes).
- **`geocode`:**
  - `in_japan` pasa a `in_country(dest.pais)`, y `regionCode` al del destino;
  - `CITY_ALIASES` pasa a `alias_ciudad` del destino;
  - las palabras genéricas traducidas de `geo.py` (shrine/santuario…) quedan comunes.
- **Normalización de nombres (`#jrNombreNorm`):** `_GENERIC_WORDS` de `text.py` se divide en una parte común (`tienda`, `store`, `shop`, `the`) y las `palabras_genericas` del destino. Para Japón el conjunto resultante es **idéntico** al actual, así que las claves no cambian.
- **`resolve` / `publish`:** sin cambios de lógica. `Layout` se resuelve a partir de `dest.raiz`, y las categorías de "Comprar y comer" a partir de `categorias_cosa`.
- **Estructura en Trilium:** la de `docs/trilium-model.md`, bajo la raíz del destino.

### 6.3 Flujo `receta` (nuevo)

Estructura en Trilium (la crea `init-trilium --destino recetas`):

```
<nota raíz>                 #<raiz>
 ├── Recetario               #jrColeccion (book, #viewType=<vista>)
 ├── Bandeja de revisión     #jrRevision
 └── Plantillas              #jrPlantillas
      └── Receta             #template + un promovido por cada entrada de `atributos`
```

- **`extract`** devuelve `RecetaExtraction`:
  - relevancia: `relacionado_destino`, `confianza_destino`;
  - datos: `titulo`, `resumen`, `raciones`, `tiempo_min`, `dificultad`, `tipo_plato`, `cocina`;
  - `ingredientes`: lista de `{cantidad, unidad, ingrediente, nota, grupo}`;
  - `pasos`: lista de textos;
  - `consejos`;
  - `portada`: índice del fotograma o imagen del plato terminado, o `null`;
  - `confianza`.
- **`cover`:** toma la imagen indicada en `portada` (si es `null` en un post, la primera imagen; en un vídeo sin elección, ninguna), la redimensiona y deja la ruta en su resultado.
- **`resolve`:**
  - Identidad: `#jrItem="<bookmark>:receta:<nombre normalizado>"`.
  - **Sin fusión entre fuentes:** dos recetas del mismo plato son notas distintas.
  - Si existe una receta con similitud de nombre ≥ `cosa_duplicate` → `posible-duplicado`.
  - Más `baja-confianza` y `clasificacion-dudosa`, como en `viaje`.
- **`publish`:**
  - La nota es hija del Recetario, con `~template=Receta` y los atributos promovidos rellenos (`sync_labels`: `probada` y `valoracion` son del usuario y no se escriben nunca).
  - Cuerpo: portada (adjunto de imagen incrustado arriba), Resumen, Ingredientes (agrupados si hay `grupo`), Preparación (lista numerada), Consejos, Fuentes y **Mis notas**.
- **Reprocesado del mismo enlace:** regenera la nota conservando "Mis notas" y los atributos corregidos por el usuario, con la regla de siempre.

### 6.4 Resultado del job y Karakeep

- `Outcome.NO_JAPON` pasa a `Outcome.DESCARTADO` → `jr:descartado`.
  - Un job descartado lo decide `classify` (ningún destino) o `extract` (no relevante para el destino).
  - `jr:no-japon` se sigue reconociendo como "ya procesado" en el ingest (cualquier `jr:*` lo es).
  - `outcome='no-japon'` en `state.db` se lee como `DESCARTADO`.
- Al marcar se añade también `jr:destino:<d>` (p. ej. `jr:destino:recetas`), salvo en `DESCARTADO` y `ERROR` sin destino. `mark` considera obsoletas solo las etiquetas de resultado y de destino distintas de las nuevas.

## 7. Errores

| Situación | Tratamiento |
|---|---|
| YAML inválido, flujo/destino/raíz/contexto inexistente | `ConfigError` en preflight; el servicio no arranca |
| Respuesta del clasificador no interpretable | 1 reintento con corrección; después, fallo temporal (backoff) → `jr:error` |
| Ningún destino / confianza baja | `DESCARTADO`, archivado |
| Duda entre dos destinos | Mejor destino + `clasificacion-dudosa` (Bandeja) |
| `QuotaExceeded(clave)` | Se aparca el job; en la pasada, las etapas con esa clave no se ejecutan; el resto sigue |
| Job en `ERROR` | No se limpia nada (diagnóstico) |

## 8. Pruebas

TDD sin red (`tests/fakes.py`, `tests/builders.py`, respx):

- **Configuración:** YAML válido/inválido, referencias cruzadas y parámetros por flujo.
- **`classify`:** omisión con un candidato, modos `json_schema` y `etiqueta`, destino inventado, `ninguno`, margen de revisión y fotogramas cuando no hay texto.
- **Pipeline:** cuota por clave (el job sin Places sigue; no se llama a la API con la clave agotada), reanudación, limpieza de ficheros, purga por retención y reprocesado de un job purgado.
- **Compatibilidad:** fixtures con JSON reales de `extract`/`geocode`/`resolve` tomados de `state.db` (formato `*_japon`); `outcome='no-japon'`; migración de `jobs`.
- **Equivalencia de Japón:** la suite actual, adaptada solo para construir el destino `japon` desde configuración, pasa **sin cambiar ninguna aserción**. `#jrNombreNorm` idéntico para una muestra de nombres reales. Antes/después con `japan-reader eval`.
- **Flujo receta:** extracción, portada, render, atributos, reprocesado con "Mis notas" y `posible-duplicado`.
- **Integración manual:** raíces de prueba `#jrRootTest` y `#jrRootRecetasTest`.

## 9. Fases de implementación

Cada fase se puede desplegar sola, deja `uv run pytest -q` en verde, actualiza sus docs (`docs/pipeline/*`, `operations.md`, `trilium-model.md`, `CLAUDE.md`) y se para para revisión manual.

| Fase | Contenido | Efecto visible |
|---|---|---|
| 0 | Renombrado a **Tohoku** (§11) | Nombre del contenedor, la CLI y los avisos |
| 1 | Cuotas por clave: la cola no se detiene | La importación avanza aunque Places esté agotado |
| 2 | `destinos.yaml` + refactor a `flows/viaje`; Japón como único destino | Ninguno (equivalencia) |
| 3 | Varias listas, `candidates`/`destination`, `classify` con modos, `reprocess --destino`, `DESCARTADO` | Solo al configurar una lista con varios destinos |
| 4 | Limpieza en dos niveles | Libera `data/jobs/` |
| 5 | Flujo `receta` + `init-trilium --destino` | Recetario en Trilium |
| 6 | Nueva Zelanda solo con configuración (valida el criterio 1) | Nota NZ en Trilium |

**Convivencia con la importación de Instagram en curso:**
- Las fases 0 y 1 pueden desplegarse ya (entre tandas).
- Las fases 2-4 tocan el núcleo: se despliegan entre tandas y se comprueba antes, con una copia de `state.db`, que los jobs pendientes reanudan en la etapa correcta.

## 10. Riesgos

- **Regresión en Japón por el refactor:** se mitiga con la suite sin cambios de aserciones, la muestra de `#jrNombreNorm` y `eval` antes/después.
- **`stage_results` antiguos incompatibles:** alias en los modelos y fixtures reales.
- **Clasificador con formato de salida no estándar (JEV):** interfaz con modos y adaptadores; punto abierto en §3.
- **Reprocesar tras la purga cuesta Whisper + LLM:** es aceptable. `retencion_dias` permite ajustarlo.
- **La vista Tabla de Trilium depende de los atributos promovidos de la plantilla:** se comprueba en integración manual con `#jrRootRecetasTest`.

## 11. Renombrado a Tohoku (fase 0)

`japan-reader` era un nombre ligado a un único destino. El proyecto pasa a llamarse **Tohoku**.

**Cambia:**
- el paquete `japan_reader` → `tohoku` (`git mv`);
- `pyproject.toml` (nombre, descripción, script `tohoku`);
- el servicio, la imagen (`tohoku:local`) y el contenedor (`tohoku`) de Docker;
- los títulos de ntfy y los mensajes de log;
- README, `CLAUDE.md`, `docs/*` y la especificación original (nota de renombrado).

**Se mantiene** (identificadores ya escritos en datos reales; renombrarlos exigiría migrar ~500 notas y ~2.300 bookmarks sin ganancia funcional):
- las etiquetas `jr:*` de Karakeep;
- los atributos `#jr*` de Trilium (`jrRoot`, `jrItem`, `jrNombreNorm`, `jrTipo`…);
- el adjunto `japan-reader.json`;
- el contenido de `state.db`.

**El prefijo `jr` es intencionado y se mantiene para todo lo que genere Tohoku:** etiquetas de Karakeep (`jr:*`) y atributos de Trilium (`#jr*`), incluidos los de destinos y flujos nuevos. Las raíces nuevas siguen la convención `jrRoot<Destino>` (`jrRootRecetas`, `jrRootNZ`). Es un homenaje doble: son las siglas de *Japan Reader*, el nombre original, y de **JR** (Japan Railways), cuya línea **Tohoku Shinkansen** da nombre al proyecto.

**Volumen de modelos:** Compose antepone el nombre del proyecto al del volumen (`japan-reader_whisper-models`). El compose declara `name: japan-reader_whisper-models` para reutilizarlo y no volver a descargar large-v3.

**Directorio del repositorio:** `/media/1tb-disk/japan-reader` → `/media/1tb-disk/tohoku`, al final de la fase, con el contenedor parado y entre tandas. Se mueve también la memoria de Claude del proyecto (su ruta depende del directorio).

**Verificación:**
- `uv run pytest -q` en verde;
- `docker compose build` y `up -d`;
- `tohoku status` dentro del contenedor muestra los mismos jobs;
- el modelo se carga desde el volumen existente sin descargar nada;
- los jobs pendientes reanudan.
