# Frontera CO — Automatización (Python / Vercel)

Migración del proyecto de Google Apps Script ("Crear carpetas" / script `1quZ25jy...`) a una
arquitectura Python modular, desplegable en Vercel. Dos motores:

- **CAPEX (Alcance Quinquenal, CREG 038/2014):** lee las actas técnicas (VIPE/INFR/NOTE/INST)
  de una frontera, extrae 14 campos técnicos por acta vía Claude, los combina, y clasifica el
  tipo de medida (directa/semidirecta/indirecta) con sus reglas de reclasificación.
- **OPEX (mano de obra):** resuelve el operador de red del CO y calcula el costo de mano de
  obra según `ref_tarifario`, derivando las maniobras directamente del alcance de equipos que
  ya calculó CAPEX (no depende de que el CO esté cargado a mano en ninguna hoja).

## Estado de la migración

| Pieza | Estado |
|---|---|
| Prompt de extracción de actas (verbatim) | ✅ `core/prompts/acta_extraction_prompt.py` |
| `acta_analyzer` / `alcance_combiner` (CAPEX) | ✅ |
| `clasificador_medida` — tipo de medida + reglas 9a/9b/9c/9d | ✅ |
| Propuesta de equipos concreta (SKUs de TC/TP/medidor/bloque/celda/cable) | ✅ `propuesta_equipos.py` + módulos de apoyo (ver abajo) |
| `tarifa_calculator` / `opex_desde_equipos` (OPEX) | ✅ |
| `operator_resolver` — hoja "Data" | ✅ |
| `operator_resolver` — fallback leyendo la acta más reciente | ✅ |

## Cómo se resuelve el operador de red (OR)

Orden de `resolver_operador_red()`: hoja "Data" (columna C, gid `1682501029`) → si no está
ahí, se busca en Metabase (Card 82534) el `act_pdf_url` de la acta VIPE/INFR/NOTE/INST más
reciente del CO, se descarga ese PDF y se le hace UNA pregunta puntual y barata a Claude
(`or_extractor.py`: `max_tokens=300, effort="low"`, mismo patrón que
`extraerRatioDeCertificadoCalibracion` en el original) → si nada de eso resuelve, queda
`fuente="pendiente_manual"` y `/api/opex_resolver` responde HTTP 202 pidiendo que el
frontend mande `or_manual`.

Se investigó primero si el OR salía de una columna de la Card 82534 vía un parámetro
`contrato` — resultó que **no**: esa card no trae ninguna columna de operador (confirmado
tanto en el código original como por Dinovi), el OR solo existe escrito dentro del texto del
acta. `contrato` sigue sin usarse en este proyecto (no hizo falta una vez se confirmó dónde
vive realmente el dato).

## Cómo se calcula la mano de obra (ref_tarifario) — verificado contra la hoja real

Se verificó `ref_tarifario` directamente en Sheets (gid `192919919`, 2026-09-21): B-I son los
8 operadores exactos ya asumidos (`CELSIA VALLE, ELECTROHUILA, ESSA, AIRE, ENEL, EMCALI,
AFINIA, OTROS_OR`), 72 maniobras en las filas 2-73. Pero las maniobras **no son plantillas
genéricas por categoría de equipo** ("Instalación de TC") — están armadas por **tipo de
medida × ubicación**, ej.:

- `Instalación semidirecta interior (medidor + bloque + módem + toma 110V si aplica)` — medidor
  y bloque de pruebas van JUNTOS en una sola maniobra, no por separado.
- `Montaje TCs MT (1–3) – exterior` — precio plano por visita (1 a 3 unidades), no por unidad.
- **"Celda" y "Cable" no tienen ninguna maniobra propia** en esta hoja — siempre quedan como
  alerta para agregar a mano; no es un bug, es que esta hoja no las factura por separado.

Por eso `opex_desde_equipos.py` NO recibe una lista genérica de "filas de equipo" — recibe
directamente lo que CAPEX ya clasificó: `tipo_medida_final` + `ubicacion` + qué `secciones`
cambian (medidor/tc/tp/bloque_pruebas) + si es instalación nueva o cambio — y usa
`tarifa_calculator.buscar_maniobra_por_palabras()`, un matcher por palabras clave exactas
(todas presentes, ninguna excluida) que solo devuelve una maniobra si el resultado es
INEQUÍVOCO — nunca "la más parecida" cuando hay ambigüedad real (ej. "medidor semidirecta
interior" aparece en dos maniobras distintas: con bloque y sin bloque; solo la palabra "bloque"
como exclusión las distingue). Ver `tests/test_tarifa_calculator.py` y
`tests/test_opex_desde_equipos.py` para los 24 casos verificados uno por uno contra la hoja real.

**Carro canasta (columna H de la hoja "OPEX")** — Dinovi, 2026-09-30: si el alcance del CO trae
montaje de TCs o TPs en **exterior** (maniobras "Montaje TCs/TPs MT … exterior"), la columna H
lleva un valor fijo de **$4.500.000** (`CARRO_CANASTA_MONTAJE_EXTERIOR` en `config/settings.py`),
**una sola vez por CO** — en la primera de esas maniobras, aunque haya TCs y TPs. No aplica a
interior, a desmontes ni a la "Instalación indirecta exterior … (sin Montaje TCs/TPs MT)" (esa
solo nombra esas palabras para aclarar que no las incluye). La regla vive en
`core/services/carro_canasta.py`; `guardar_opex.py` la aplica al escribir y `opex_desde_equipos.py`
la suma al total de la vista previa. Como esa celda deja de ser fórmula, la fila siguiente (que
se crea copiando la anterior) la heredaría: por eso al guardar se restaura la fórmula de H en toda
fila que no lleve el valor.

**Descargo (columna I de la hoja "OPEX")** — Dinovi, 2026-09-30: si el alcance del CO trae montaje
de TCs o TPs, **interior o exterior**, la columna I lleva un valor fijo: **$8.000.000** para todos
los operadores (OR) salvo **ENEL, que lleva $12.000.000** (`DESCARGO_MONTAJE_TC_TP` y
`DESCARGO_MONTAJE_TC_TP_ENEL` en `config/settings.py`). Igual que el carro canasta, va **una sola
vez por CO**, en la primera maniobra de montaje, y no aplica a desmontes ni a las instalaciones que
solo nombran "Montaje TCs/TPs" para aclarar que no lo incluyen. La regla vive en
`core/services/descargo.py` (comparte el detector de montaje con `carro_canasta.py`). Si el OR no
se puede normalizar a una de las 8 columnas del tarifario, cuenta como "no ENEL" ($8.000.000).

⚠️ También se corrigió que `sheets_client.py` pedía los valores "tal como se ven" (ej.
`"$118,750.00"`) en vez del número crudo — eso habría hecho que CADA precio quedara en 0 al
intentar convertir ese texto a `float`. `leer_todo`/`leer_rango` ahora aceptan
`sin_formato=True` (UNFORMATTED_VALUE) para columnas numéricas.

## Motor de propuesta de equipos (CAPEX) — 3 hojas externas + catálogo

`propuesta_equipos.py` es el puerto de `construirPropuestaEquipos` (Codigo.gs, 713 líneas) —
a partir del diagnóstico de `clasificador_medida` + el veredicto de Lovable, decide qué SKU de
`ref_capex` proponer para TC/TP/medidor/bloque de pruebas/celda/cable. Depende de 3 hojas
externas, todas **confirmadas visualmente** contra la hoja real el 2026-09-22 (no solo contra
comentarios del código):

| Hoja | Dónde vive | Para qué sirve |
|---|---|---|
| "Data cambio NT" | Libro `NTCAMBIO_SHEET_ID`, gid `1941841015` | CO ya pasó cambio de Nivel de Tensión (Art.19) — SKU ya calculado a mano por ingeniería |
| "Normalizaciones_Indirectas" | Mismo libro, gid `821330837` | Relación de TC/TP + cantidad ya calculada, prioridad sobre "Data cambio NT" |
| "BD_Telemedida" (hoja maestra) | Libro `CONTROL_SHEET_ID`, gid `655267373` | Única con una fila por CADA CO — sirve cuando no hay ninguna acta disponible (medida, conexión, Factor Fx, capacidad) |

**Bug real corregido en `hojas_ingenieria.py`**: la columna "Propiedad de Activos" de la hoja
maestra casi nunca dice literalmente "Exclusivo"/"Compartido" — los valores reales son **"OR"**
(activo del operador de red → compartido) y **"Usuario"** (activo del cliente → exclusivo). El
original solo buscaba las palabras "exclusiv"/"compartid" como substring, así que para la
inmensa mayoría de filas esto quedaba en `null` sin que nadie lo notara — confirmado en vivo
con CO0200002425 (Lovable mostraba el uso correcto, el diagnóstico automático no).

**2 bugs preexistentes encontrados y documentados con test (no corregidos — son del original,
requieren tu decisión)**:
- `parsear_medidor`: `\bC2000\b`/`\bD2000\b` nunca hacen match contra SKUs reales como
  `"C2000Cor5 (100) AT"` (no hay borde de palabra entre "2000" y "Cor5"). Ver
  `test_parsear_medidor_bug_preexistente_c2000_pegado_al_sufijo`.
- `parsear_tp`: el símbolo "√3" dobla un dígito real dentro del primario (`"13200√3"` →
  `132003` en vez de `13200`), así que `buscarCandidatosTP` nunca encuentra estos ítems reales
  del catálogo. Ver `test_parsear_tp_bug_preexistente_raiz_3_corrompe_el_primario`.

El caso real **CO0200002425** (semidirecta, transformador compartido, TC sin certificado →
condición: cambiarlo) quedó como test de integración en `test_propuesta_equipos.py`,
reproduciendo exactamente el SKU/precio que se validó a mano con Dinovi.

## Orquestador final — `/api/analizar_alcance`

`alcance_provisional.py` es el puerto de `analizarAlcanceProvisional`: ata acta (ya combinada
por el job async) + hoja maestra + Data cambio NT + Normalizaciones_Indirectas + certificado
de calibración (`certificado_extractor.py`, mismo patrón que `or_extractor.py`) +
clasificación + catálogo, y entrega la propuesta final + las alertas en cascada del original
(sin acta INST, capacidad/TC en desacuerdo entre actas, ubicación asumida por OR, etc.).

A diferencia del original, **no lee actas por dentro** — `POST /api/analizar_alcance` exige
que el job de `/api/actas_start` + `/api/actas_step` ya esté `completo` para ese CO (o que
`dictamen.sinActas=true`), para no repetir ese trabajo ni arriesgar timeout en cada llamada.
Body: `{"co", "dictamen": {clasificacion, capacidadIncierta?, sinActas?, seccionesForzadas?,
detalleFaltante?}}` — mismo JSON que ya arma Index.html en el original.

⚠️ **Gap conocido, no corregido todavía**: el original usa `dictamen.capacidadIncierta` para
decidir si sigue escaneando actas viejas buscando un SEGUNDO valor de capacidad para cruzar
(`necesitaMasCapacidad`, Codigo.gs línea 3288). El job asíncrono (`alcance_combiner.py`) no
implementa ese cruce todavía — solo se detiene cuando los campos obligatorios ya están
completos. No afecta la corrección del resultado (nunca inventa nada), solo que no avisa
proactivamente si dos actas declaran capacidades distintas cuando la primera ya alcanzó para
completar el spec.

## Estructura

```
/api                      → endpoints serverless de Vercel (uno por responsabilidad, ver nota abajo)
  index.py                  → entrypoint único que registra los 6 Blueprints (ver nota abajo)
  actas_start.py            → crea el job de actas de un CO y procesa la primera
  actas_step.py             → procesa UNA acta más del job (el frontend hace polling)
  actas_status.py           → progreso/resultado actual, sin avanzar el job
  analizar_alcance.py       → orquestador final: acta+hojas+catálogo -> propuesta de equipos
  opex_resolver.py          → operador + mano de obra de un CO (síncrono, sin LLM)
  cron_reintentos.py        → red de seguridad: avanza jobs que quedaron a medias
/core
  /data_sources
    sheets_client.py          → Google Sheets vía cuenta de servicio (reemplaza SpreadsheetApp)
    metabase_client.py        → Card 82534, CSV completo + filtro client-side, retry+backoff
    llm_client.py              → wrapper de la API de Anthropic, retry+backoff
  /prompts
    acta_extraction_prompt.py  → ALCANCE_EXTRACTION_PROMPT, verbatim y versionado
    or_extraction_prompt.py    → pregunta puntual y barata: solo el Operador de Red de un acta
  /validators
    alcance_schema.py           → parseo RESUMEN/JSON + normalización de los 14 campos
  /services
    acta_downloader.py           → descarga/valida PDF de act_pdf_url (incluye .zip)
    acta_ocr.py                   → OCR vía Drive API (equivalente a Drive.Files.create ocr:true)
    acta_analyzer.py               → CAPEX: UNA acta -> 14 campos (módulo puro)
    alcance_combiner.py             → CAPEX: combina actas de un CO, una por invocación
    clasificador_medida.py           → CAPEX: tipo de medida + reglas de dominio
    catalogo_capex.py                 → CAPEX: parseo de SKUs de ref_capex (TC/TP/medidor)
    tablas_creg.py                     → CAPEX: tablas oficiales CREG 038/2014 para TC (semidirecta/indirecta)
    hojas_ingenieria.py                 → CAPEX: Data cambio NT / Normalizaciones_Indirectas / hoja maestra
    deteccion_equipos.py                 → CAPEX: qué hay instalado (Metabase) + qué secciones están deficientes
    resolucion_tc_tp.py                   → CAPEX: candidatos de TC/TP/medidor/celda + reglas por OR (EPM, EMCALI, Air-e)
    propuesta_equipos.py                   → CAPEX: orquestador (puerto de construirPropuestaEquipos)
    propuesta_equipos_contexto.py           → CAPEX: arma el contexto compartido por los resolutores
    propuesta_tc.py / propuesta_tc_calculo.py → CAPEX: resolución de TC (la rama más compleja)
    propuesta_tp_medidor.py                   → CAPEX: resolución de TP y Medidor
    propuesta_bloque_celda_cable.py             → CAPEX: resolución de Bloque de pruebas, Celda y Cable
    hoja_origen_equipos.py                        → CAPEX: hoja "Data" (cliente/OR/maniobra) + hoja "Equipos" existente
    certificado_extractor.py                       → CAPEX: relación certificada de un TC/TP ya instalado (módulo puro)
    alcance_provisional.py                          → CAPEX: orquestador final (puerto de analizarAlcanceProvisional)
    tarifa_calculator.py              → OPEX: normalización + matcher por palabras clave contra ref_tarifario
    opex_desde_equipos.py             → OPEX: maniobras por tipo de medida × ubicación (verificado contra la hoja real)
    operator_resolver.py              → OPEX: hoja "Data" -> acta más reciente -> manual
    or_extractor.py                   → OPEX: extrae el OR de UN acta (módulo puro)
    job_store.py                       → estado intermedio por CO (hoja "PyAsyncJobs")
    wiring.py                          → construye los clientes desde variables de entorno
  utils.py                    → normalizar_codigo / quitar_acentos (compartido)
/config
  settings.py                → carga de variables de entorno, sin defaults inventados
/tests                       → mocks de LLM/Metabase/Sheets, sin dependencias reales
```

## Por qué `api/index.py` (entrypoint único) y no un `app = Flask(__name__)` por archivo

El diseño original tenía una app Flask independiente por archivo en `/api`. Al desplegar,
Vercel detecta Flask como "framework" en cuanto ve más de un `app = Flask(__name__)` bajo
`/api/*.py`, y en ese modo exige un único entrypoint (falla con
`No Flask entrypoint found in default locations`). Por eso cada archivo expone un
`Blueprint` (`bp = Blueprint(...)`) en vez de su propia app, `api/index.py` los registra
todos en una sola `Flask(__name__)`, y `pyproject.toml` declara
`[tool.vercel] entrypoint = "api.index:app"`. Las rutas (`/api/actas_start`, etc.) no cambian.

## Qué acta se lee de cada CO (Dinovi, 2026-10-01)

**UNA sola acta por CO**, elegida por `alcance_combiner.seleccionar_actas_ordenadas`:
1. La **INFR de una visita exitosa** (la más reciente si hay varias).
2. Si no hay INFR exitosa, la **más reciente de cualquier tipo** (VIPE/NOTE/INST/…) que sea exitosa.
3. Si ninguna visita con acta fue exitosa, el CO queda "sin acta" (el frontend pasa al modo "sin actas"
   y usa la hoja maestra / Data cambio NT; el mensaje lista los `estado_visita` que sí encontró).

**Respaldo SOLO por falla técnica.** La cola de actas va en ese orden de preferencia (INFR primero, luego
las demás de la más reciente a la más vieja; máx. `MAX_ACTAS_A_ESCANEAR` = 3 candidatas) y se lee la
primera. Si no se pudo leer — el PDF no se descarga o es inválido, pesa demasiado, el OCR de Drive falla,
o el acta no trae ningún dato útil — se prueba la siguiente candidata. En cuanto una acta se lee bien
termina el CO, **aunque falten campos** (nunca se sigue leyendo por campos faltantes). En la muestra de
la primera prueba, 3 de 10 COs tenían un acta ilegible, y sin este respaldo habrían quedado sin nada.

"Exitosa" = la columna `estado_visita` de la Card 82534 de Metabase vale `Cierre Exitoso` (se compara sin
importar mayúsculas, acentos ni espacios). Si la tarjeta no trae esa columna se falla con un error claro
en vez de dejar todos los CO sin acta en silencio.

Antes se leían hasta 5 actas, la más nueva primero, hasta completar los campos obligatorios: eso
multiplicaba por 2-5 las llamadas a Claude. **Consecuencia aceptada:** lo que el acta leída no traiga
(p. ej. la relación del TC) queda vacío en vez de completarse con una acta más vieja. No se tocó cómo se
resuelve el operador de red (`operator_resolver.py`, que sigue usando el acta con PDF más reciente).

## Por qué "una acta por invocación" (y no un endpoint que procese todo el CO)

(El razonamiento de abajo es de cuando se leían hasta 5 actas por CO; hoy es UNA, pero el tiempo por
acta sigue siendo impredecible y por eso cada acta sigue siendo su propia invocación.)

Una frontera podía tener hasta 5 actas (`MAX_ACTAS_A_ESCANEAR`, hoy 1), y cada una puede necesitar
hasta 2 llamadas al LLM (texto OCR, y PDF completo con imágenes como fallback) más una
descarga de hasta 20MB y un OCR vía Drive. El propio `Codigo.gs` ya documentaba esto como un
riesgo de timeout real incluso con los 30 minutos de límite de Apps Script (ver comentario
junto a `PRESUPUESTO_MS_ACTAS`, Codigo.gs línea 3252-3259) — el tiempo por acta es
**impredecible**, no hay un "peor caso" fijo sobre el que calcular un `maxDuration` seguro.

Por eso `/api/actas_start` y `/api/actas_step` procesan **una sola acta por invocación**,
guardando el progreso combinado en la hoja `PyAsyncJobs` (mismo principio que la hoja
`AsyncJobs` que el propio Apps Script ya usaba para su patrón de job asíncrono). El frontend
hace polling a `/api/actas_step` hasta recibir `completo: true`; `/api/cron_reintentos` es la
red de seguridad para jobs que quedaron a medias si el frontend se desconecta.

**Corriendo en plan Hobby** (confirmado, 2026-09-23: sin acceso a Pro): el cron de
`vercel.json` quedó en `"0 8 * * *"` (una vez al día) — Vercel rechaza cualquier frecuencia
mayor en Hobby con un error explícito al desplegar. Es una degradación aceptada: la red de
seguridad revisa jobs colgados una vez al día en vez de cada 5 min; el polling del frontend
sigue siendo el mecanismo principal, esto es solo el respaldo. Sobre `maxDuration`: Vercel no
dio ningún error de validación al respecto (solo del cron), así que se dejó tal cual —
confírmalo en el primer `vercel --prod` real; si sí llega a fallar, hay que bajarlo y aceptar
que actas muy grandes (modo imagen, PDFs pesados) pueden fallar por timeout en vez de
completarse — la fila entera de actas pendientes queda intacta para reintentar más tarde, no
se pierde progreso ya combinado.

`/api/opex_resolver` sí es síncrono: no llama al LLM ni descarga nada, solo lee hojas y hace
fuzzy-match de texto en memoria — no hay riesgo de timeout ahí.

## Consumo de la API de Claude (pestaña "Consumo" / hoja "PyConsumo")

Dinovi, 2026-10-01: la app no medía lo que gastaba en Claude, así que todo costo era un estimado.
Ahora **cada llamada a Claude deja una fila** en la pestaña `PyConsumo` de la hoja de Alcances (se
crea sola): tokens de entrada / de caché / de salida / de razonamiento, `stop_reason`, intentos y
cuántos fallaron, segundos, modelo, esfuerzo, el CO y el tipo de llamada (`acta_texto`, `acta_pdf`,
`operador`, `certificado`), el origen (`individual` | `lote`) y el costo estimado. La pestaña
**Consumo** de la pantalla (`GET /api/consumo_resumen[?desde=AAAA-MM-DD]`) lo resume: costo medio por
CO, proyección para 100/400 COs, aciertos del caché, respuestas cortadas por `max_tokens`, reintentos,
y una tabla por modelo+esfuerzo para comparar el antes y el después de un cambio.

- El registro es "mejor esfuerzo": si Sheets falla, se anota en el log de Vercel y la extracción
  sigue igual (`core/data_sources/llm_client.py` → `_registrar`, `core/services/consumo.py`).
- El costo es una **estimación** con `PRECIOS_USD_POR_MTOK` (`config/settings.py`, precios oficiales
  leídos el 2026-10-01); si cambian los precios o el modelo, se actualiza ahí. El valor exacto de la
  factura está en la consola de Anthropic.
- Mide, no ahorra: sirve para decidir con datos (¿el caché funciona?, ¿hay respuestas cortadas o
  reintentos pagados?, ¿cuánto cuesta un CO?) antes de tocar modelo o esfuerzo.

## Comparar modelos (pestaña "Comparar modelos" / `POST /api/comparar_config`)

Para bajar el costo sin perder calidad hay que poder **medir la calidad**: esta pestaña convierte el
cambio de modelo/esfuerzo en una prueba. Por cada CO toma la acta que leería producción (ver "Qué acta se lee de cada CO"), la descarga y la lee con
OCR UNA vez, y corre la extracción de producción (`analizar_acta_desde_texto`, mismo prompt y mismo
código) sobre ese MISMO texto con la configuración actual y con 1-3 candidatas (Opus 5.5, Sonnet 5.5,
distintos esfuerzos — `CONFIGS_CANDIDATAS` en `core/services/comparador.py`; Haiku 4.5 queda fuera
porque no acepta `effort`). Compara los 12 campos técnicos (`observaciones`/`supuestos` son texto libre
y no cuentan) y muestra por candidata: campos que coinciden, actas idénticas, fallos, costo frente a la
actual y tiempo.

- **La configuración actual es la referencia, no la verdad.** Una diferencia puede ser un error de la
  candidata o uno de la actual: se revisa contra el acta (la pestaña trae el enlace). La herramienta
  no decide sola.
- Además de modelo y esfuerzo, una candidata puede cambiar el **prompt**. V1/V2 le pedían a Claude escribir cada
  campo DOS veces (un bloque `RESUMEN:` de una línea por campo y luego el JSON) y el código solo lee el JSON.
  **V3** (`ACTA_EXTRACTION_PROMPT_V3`) es V2 pidiendo solo el JSON: es el que usa producción (2026-10-01) para
  leer las actas por TEXTO. En la prueba con Opus 5 / esfuerzo medio salieron 3 de 3 actas idénticas y ≈ −11 %
  de costo. La lectura por PDF (rara: solo si el texto no se pudo extraer) sigue con V2 porque el cambio no se midió
  sobre PDF. La candidata `opus-5-prompt-anterior` es un control: Opus 5 con V2; sirve para volver a confirmar, con
  más actas, que quitar el RESUMEN no cambió lo extraído.
- Una acta por llamada (cabe en los 60 s de Vercel); las candidatas corren en paralelo en hilos. Igual que
  producción, si el acta elegida no se puede descargar o leer prueba la siguiente (mientras quede tiempo) y lo
  avisa (`omitidas`). Presupuesto de 55 s: lo que quede tras leer el acta es el tiempo de Claude (un solo
  intento) y, si no alcanza, no se llama a Claude.
- **Gasta API** (≈ una extracción por configuración y acta; la pestaña estima el costo y pide
  confirmación). No escribe en las hojas de trabajo; solo deja el consumo en `PyConsumo` con
  origen `comparacion`. Los resultados viven en la pantalla: si cierras la pestaña se pierden (el
  costo no).
- Uso recomendado: 20 a 30 COs que incluyan casos difíciles (OCR malo, actas incompletas); con menos no se
  puede concluir. Solo después de revisar las diferencias se cambia el modelo/esfuerzo de producción
  (`AnthropicConfig` en `config/settings.py`).

## Correr localmente

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # y completa los valores reales
pytest
```

Los tests **no** llaman a Anthropic, Metabase ni Google Sheets reales — todo está mockeado.

Para probar un endpoint localmente con el runtime de Vercel:

```bash
npm install -g vercel
vercel dev
```

## Desplegar en Vercel

1. `vercel link` (o `vercel` la primera vez) en la raíz del repo.
2. Configura las variables de entorno en el proyecto de Vercel (Settings → Environment
   Variables), con los mismos nombres de `.env.example` — nunca las subas al repo.
3. `vercel --prod`.

El cron de `/api/cron_reintentos` se activa solo con el despliegue — no hace falta
configurarlo aparte de lo que ya está en `vercel.json`. En plan Hobby corre una vez al día
(ver nota arriba); en Pro se puede subir la frecuencia editando el `schedule`.

## Cuenta de servicio de Google

Crea una cuenta de servicio con el rol mínimo necesario (Sheets API + Drive API habilitadas
en el proyecto de GCP), y comparte la hoja de Alcances (`ALCANCE_SHEET_ID`) con su
`client_email` como Editor. El mismo service account se usa para Sheets y para el OCR vía
Drive (`acta_ocr.py` pide el scope `drive` completo porque necesita crear y borrar el archivo
temporal de OCR).
