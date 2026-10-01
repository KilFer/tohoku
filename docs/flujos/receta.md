# Flujo `receta`

**Qué hace:** convierte un Reel, Short o post de Instagram de cocina en **una nota de receta** (ingredientes, pasos, consejos, portada) dentro del Recetario de Trilium. Un enlace = una receta. No hay fusión entre fuentes: dos enlaces con la misma receta dan dos notas, y si el título se parece mucho la nueva va a la Bandeja como `posible-duplicado`.

Se activa con un destino de `config/destinos.yaml` con `flujo: receta`. Las etapas comunes (`fetch`, `transcribe`, `classify`) son las de siempre; las propias del flujo son `extract → cover → resolve → publish`. Estado: implementado en `feat/tohoku` (fase 5), sin desplegar.

## Estructura en Trilium

    Recetas                           #jrRootRecetas (la raíz la creas tú a mano)
     ├── Recetario                    #jrColeccion (book, #viewType=<vista>)
     │    └── <Receta>                #jrTipo=receta #jrItem #jrNombreNorm (~template=Receta)
     ├── Bandeja de revisión          #jrRevision
     └── Plantillas                   #jrPlantillas
          └── Receta                  #template + atributos promovidos

Detalle de la nota en `docs/trilium-model.md`. `tohoku init-trilium --destino recetas` crea lo que falte (idempotente).

## Etapas

| Etapa | Qué hace |
|---|---|
| `extract` | LLM multimodal (`config/prompts/recetas.md`, sin marcadores): relevancia (`relacionado_destino`, `confianza_destino`), título, resumen, ingredientes (con `grupo`), pasos, consejos, atributos y `portada` (índice entre imágenes + fotogramas). Necesita los ficheros del job. |
| `cover` | Elige la imagen de portada y la guarda como `cover.jpg` (lado máximo `IMAGE_MAX_SIDE`). Un post sin `portada` usa su primera imagen; un vídeo sin `portada` no tiene. |
| `resolve` | Decide: no es receta → sin elementos (`descartado`); si no, un solo elemento con motivos de revisión (`clasificacion-incierta`, `clasificacion-dudosa`, `baja-confianza`, `posible-duplicado`). Extracción fallida → nota de fallo en la Bandeja. |
| `publish` | Crea o actualiza la nota (identidad `#jrItem="<bookmark>:receta:<name_key(título)>"`; al reprocesar se retoma la nota del mismo enlace aunque cambie el título), sube la portada como adjunto, conserva "Mis notas" y sincroniza la Bandeja. |

## Configuración

    recetas:
      flujo: receta
      raiz: jrRootRecetas
      descripcion: "Recetas de cocina: ..."
      prompt: prompts/recetas.md
      vista: table                  # table | grid | list
      # opcionales; por defecto: tipo_plato, cocina, tiempo_min, raciones, dificultad, probada, valoracion
      atributos: {tipo_plato: text, cocina: text, probada: boolean}   # promovidos de la plantilla (text|number|boolean)
      atributos_usuario: [probada]                                    # nunca los escribe el servicio

- El servicio solo **escribe** los atributos que son campos de la extracción (`tipo_plato`, `cocina`, `tiempo_min`, `raciones`, `dificultad`), y respeta los que corrijas tú (misma regla que en viaje). `atributos_usuario` no se escriben nunca. Cualquier otro atributo que añadas a mano es tuyo.
- `atributos` solo se aplica al crear la plantilla: `init-trilium` **no añade** atributos promovidos nuevos a una plantilla `Receta` existente (añádelos a mano en Trilium).
- Cómo activarlo: ver "Activar Recetas" en `docs/operations.md`.

## Fallos

- Falta algo del Recetario → `ConfigError` en el preflight ("ejecuta `tohoku init-trilium --destino …`").
- Extracción inválida tras el reintento → nota `jrTipo=fallo` en la Bandeja, motivo `extraccion-fallida`.
- Contenido que no es una receta → `descartado`: sin nota y sin etiqueta `jr:destino:<d>`.
- La portada falla al subirse (error transitorio) → el job se reintenta; la nota no queda duplicada (idempotente vía `#jrItem`).
- Reels de Instagram con restricción de audiencia o "empty media": igual que en el flujo viaje (docs/pipeline/02-fetch.md).

## Cómo probarlo

- Sin red: `uv run pytest tests/unit/test_flow_receta.py tests/unit/test_receta_*.py`.
- Integración manual (con confirmación, usa servicios reales): nota `#jrRootRecetasTest`, `init-trilium --destino recetas` y 2-3 Reels de recetas; comprobar a mano la vista Tabla y la portada. Reprocesar con `reprocess <id> --from extract` (también repite `cover`).
