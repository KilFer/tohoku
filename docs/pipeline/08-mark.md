# Etapa 8 — mark

**Qué hace:** deja constancia del resultado en Karakeep y limpia la Home.

**Entrada:** `bookmark_id` y el resultado (`Outcome`) calculado por `publish`, o `error`.
**Salida:** `MarkResult {tag, archived}`.
**Dependencias:** Karakeep (`GET /bookmarks/{id}`, `POST/DELETE /bookmarks/{id}/tags`, `PATCH /bookmarks/{id}`).

| Resultado | Etiqueta | Archivar |
|---|---|---|
| procesado | `jr:procesado` | sí |
| revisar | `jr:revisar` | sí |
| no-japon | `jr:no-japon` | sí |
| error | `jr:error` | no |

Quita cualquier otra etiqueta `jr:*` anterior (útil al reprocesar). El resto de etiquetas del usuario no se tocan.

**Fallos:** red/5xx → reintento del job (las etapas anteriores no se repiten); si falla marcando un error definitivo, el job queda en error igualmente y se registra en el log.

**Cómo probarla:** `uv run pytest tests/unit/test_ingest_mark.py -k mark`.
