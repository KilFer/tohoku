# Etapa 8 — mark

[English](08-mark.md) · **Español**

**Qué hace:** deja constancia del resultado en Karakeep y limpia la Home.

**Entrada:** `bookmark_id` y el resultado (`Outcome`) calculado por `publish`, o `error`.
**Salida:** `MarkResult {tag, archived}`.
**Dependencias:** Karakeep (`GET /bookmarks/{id}`, `POST/DELETE /bookmarks/{id}/tags`, `PATCH /bookmarks/{id}`).
**Configuración:** `KARAKEEP_URL`, `KARAKEEP_API_KEY`. La etapa no tiene ajustes propios; las etiquetas son fijas (ver tabla).

| Resultado | Etiqueta | Archivar |
|---|---|---|
| procesado | `jr:procesado` | sí |
| revisar | `jr:revisar` | sí |
| descartado | `jr:descartado` | sí |
| error | `jr:error` | no |

Además añade `jr:destino:<destino>` con el destino decidido por `classify`, salvo en `descartado`: **un `descartado` nunca lleva `jr:destino`**, ni cuando `classify` no eligió destino ni cuando el flujo del destino descarta el contenido (p. ej. el flujo `viaje` con contenido que no es de ese país). Un `error` lo lleva solo si el job ya tenía destino. Quita las etiquetas `jr:` de resultado o de destino anteriores que difieran de las nuevas (útil al reprocesar). El resto de etiquetas del usuario no se tocan.

**Fallos:** red/5xx → reintento del job (las etapas anteriores no se repiten); si falla marcando un error definitivo, el job queda en error igualmente y se registra en el log.

**Cómo probarla:** `uv run pytest tests/unit/test_ingest_mark.py -k mark`.
