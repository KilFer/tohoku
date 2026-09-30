# Modelo de datos en Trilium

La raíz es la nota **`Home › Viajes › Ideas de Japón`**, marcada a mano una vez con `#jrRoot`. El servicio encuentra todo por atributos, así que puedes mover o renombrar las notas.

El prefijo `jr` de todos los atributos y del adjunto `japan-reader.json` viene del nombre original del proyecto (*japan-reader*, hoy Tohoku) y se mantiene a propósito.

    Ideas de Japón                    #jrRoot
     ├── Mapa de lugares              #jrMapa   (book + ~template=_template_geo_map → Geo Map)
     ├── Comprar y comer              #jrComprar
     │    └── Souvenirs · Comida · Cadenas · Cosmética · Otros   #jrCategoria=<clave>
     ├── Cultura y curiosidades       #jrCultura
     ├── Bandeja de revisión          #jrRevision
     └── Plantillas                   #jrPlantillas
          ├── Lugar                   #template (+ definiciones promovidas: visitado, prioridad, ciudad, categoria)
          └── Cosa                    #template (+ comprado, categoria)

`tohoku init-trilium` crea lo que falte (idempotente).

## Nota Lugar (hija de "Mapa de lugares")

- **Atributos gestionados:** `#jrItem="<bookmark_id>:<identidad>"` (identidad del elemento **por contenido**, no por posición: `b1:lugar:<place_id>` si tiene ficha de Google, `b1:lugar:n:<nombre normalizado>` si no; primer atributo que se escribe, para poder retomar una creación cortada a medias sin duplicar), `#geolocation="lat,lng"`, `#googlePlaceId`, `#googleMaps`, `#ciudad`, `#region`, `#categoria`, `#nombreLocal`, `#fuentes`, `#iconClass`, `#jrTipo=lugar`, `#jrNombreNorm` (nombre normalizado; clave de deduplicación de los lugares sin ficha de Google), `~template=Lugar`.
- **Atributos tuyos (nunca se tocan):** `#visitado`, `#prioridad` y cualquier otro que añadas.
- **Cuerpo:** Resumen · Qué hacer / comer · Consejos prácticos · enlace a Google Maps · Fuentes · **Mis notas**.

## Nota Cosa (hija de su categoría en "Comprar y comer")

- **Atributos:** `#jrItem="<bookmark_id>:cosa:<nombre normalizado>"`, `#jrTipo=cosa`, `#jrNombreNorm` (nombre normalizado, clave de deduplicación), `#categoria`, `#fuentes`, `#iconClass`, `~template=Cosa`, `~dondeComprar` → notas Lugar cuando la fuente recomienda un local concreto.
- **Cuerpo:** Resumen · Dónde conseguirlo · Consejos · Fuentes · **Mis notas**.

## Nota Otro (hija de "Cultura y curiosidades")

Título + contenido + fuentes. Sin deduplicación. Lleva `#jrItem="<bookmark_id>:otro:<título normalizado>"`. La nota sintética (contenido de Japón sin elementos) se titula con el título de la fuente; si está vacío, con la primera línea de la descripción (máx. 80 caracteres); si tampoco hay, "Sin título".

## Nota de extracción fallida (en "Bandeja de revisión")

Lleva `#jrItem="<bookmark_id>:fallo"` y `#jrTipo=fallo`. Cuerpo: enlace, error, descripción y transcripción.

## Datos estructurados

Cada nota lleva un adjunto `japan-reader.json` con sus datos (resumen, consejos, fuentes, ficha de Google). Es la fuente de verdad para las fusiones: no lo borres.

## Reglas de fusión

- **Lugar:** mismo `#googlePlaceId` → misma nota; si no, mismo `#jrNombreNorm` con el pin a menos de 300 m (dos fichas de Google para el mismo sitio) → misma nota; sin ficha de Google, mismo `#jrNombreNorm`. Se añade la fuente, `#fuentes` sube y el LLM reescribe Resumen, Qué hacer y Consejos integrando lo nuevo.
- **Cosa:** mismo `#jrNombreNorm` → misma nota. Si hay una parecida pero no idéntica (similitud ≥ 0.85), se crea una nota nueva y se manda a revisión (`posible-duplicado`).
- **Misma fuente otra vez** (reprocesado): su entrada se actualiza; no se duplica ni se llama al LLM. Si la nota **solo** tiene esa fuente, se regenera entera con la extracción nueva (conservando la ficha de Google si la nueva no la trae, y siempre "Mis notas"). Si otras fuentes también contribuyeron, solo se sustituye la entrada de esta fuente.
- **Clave natural antes de crear:** aunque el plan diga `create`, si ya existe una nota con el mismo `#googlePlaceId` (lugar) o `#jrNombreNorm` (cosa), se fusiona en ella.
- **Atributos gestionados que corriges tú:** si cambias o corriges un atributo gestionado (`#geolocation`, `#googleMaps`, `#categoria`, `#ciudad`, `#iconClass`...), las fusiones siguientes lo respetan: solo se reescribe si falta o si aún tiene el valor que escribió el servicio. `#fuentes` y `#jrTipo` se escriben siempre.
- **Mis notas:** todo lo que haya debajo del encabezado "Mis notas" se conserva siempre. Si borras el encabezado, en la siguiente fusión todo el contenido anterior pasa debajo de un "Mis notas" nuevo.

## Bandeja de revisión

Las notas dudosas se **clonan** en la bandeja (siguen también en su sitio) con `#revisar=<motivos>`: `geocodificacion-fallida`, `geocodificacion-ambigua`, `posible-duplicado`, `baja-confianza`, `clasificacion-incierta`, `extraccion-fallida`. Revisar = corregir la nota, quitar `#revisar` y quitar el clon de la bandeja. El servicio no vuelve a meter en la bandeja una nota que el usuario sacó salvo que llegue una fuente nueva con motivos; y la saca él mismo si un reprocesado resuelve todos sus motivos.
