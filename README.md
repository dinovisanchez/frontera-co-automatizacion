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
| Propuesta de equipos concreta (SKUs de TC/TP/medidor) | ⏳ Siguiente incremento — depende de `ref_capex` y `Normalizaciones_Indirectas`, fuera del alcance confirmado inicial |
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

## Estructura

```
/api                      → endpoints serverless de Vercel (uno por responsabilidad)
  actas_start.py            → crea el job de actas de un CO y procesa la primera
  actas_step.py             → procesa UNA acta más del job (el frontend hace polling)
  actas_status.py           → progreso/resultado actual, sin avanzar el job
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
    tarifa_calculator.py              → OPEX: fuzzy-match + ref_tarifario
    opex_desde_equipos.py             → OPEX: maniobras derivadas del alcance de equipos
    operator_resolver.py              → OPEX: hoja "Data" -> acta más reciente -> manual
    or_extractor.py                   → OPEX: extrae el OR de UN acta (módulo puro)
    job_store.py                       → estado intermedio por CO (hoja "PyAsyncJobs")
    wiring.py                          → construye los clientes desde variables de entorno
  utils.py                    → normalizar_codigo / quitar_acentos (compartido)
/config
  settings.py                → carga de variables de entorno, sin defaults inventados
/tests                       → mocks de LLM/Metabase/Sheets, sin dependencias reales
```

## Por qué "una acta por invocación" (y no un endpoint que procese todo el CO)

Una frontera puede tener hasta 5 actas (`MAX_ACTAS_A_ESCANEAR`), y cada una puede necesitar
hasta 2 llamadas al LLM (texto OCR, y PDF completo con imágenes como fallback) más una
descarga de hasta 20MB y un OCR vía Drive. El propio `Codigo.gs` ya documentaba esto como un
riesgo de timeout real incluso con los 30 minutos de límite de Apps Script (ver comentario
junto a `PRESUPUESTO_MS_ACTAS`, Codigo.gs línea 3252-3259) — el tiempo por acta es
**impredecible**, no hay un "peor caso" fijo sobre el que calcular un `maxDuration` seguro.

Por eso `/api/actas_start` y `/api/actas_step` procesan **una sola acta por invocación**,
guardando el progreso combinado en la hoja `PyAsyncJobs` (mismo principio que la hoja
`AsyncJobs` que el propio Apps Script ya usaba para su patrón de job asíncrono). El frontend
hace polling a `/api/actas_step` hasta recibir `completo: true`; `/api/cron_reintentos` (cada
5 min, ver `vercel.json`) es la red de seguridad para jobs que quedaron a medias si el
frontend se desconecta.

`/api/opex_resolver` sí es síncrono: no llama al LLM ni descarga nada, solo lee hojas y hace
fuzzy-match de texto en memoria — no hay riesgo de timeout ahí.

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
3. Los `maxDuration` de 60s en `vercel.json` para `actas_start`/`actas_step`/`cron_reintentos`
   requieren como mínimo el plan **Pro** de Vercel (Hobby tope 10s no alcanza ni para una
   sola acta en modo imagen).
4. `vercel --prod`.

El cron de `/api/cron_reintentos` se activa solo con el despliegue — no hace falta
configurarlo aparte de lo que ya está en `vercel.json`.

## Cuenta de servicio de Google

Crea una cuenta de servicio con el rol mínimo necesario (Sheets API + Drive API habilitadas
en el proyecto de GCP), y comparte la hoja de Alcances (`ALCANCE_SHEET_ID`) con su
`client_email` como Editor. El mismo service account se usa para Sheets y para el OCR vía
Drive (`acta_ocr.py` pide el scope `drive` completo porque necesita crear y borrar el archivo
temporal de OCR).
