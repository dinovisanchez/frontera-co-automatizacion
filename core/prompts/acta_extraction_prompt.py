"""System prompt para extraer los 14 campos técnicos de UN acta (VIPE/INFR/NOTE/INST).

Portado PALABRA POR PALABRA desde ALCANCE_EXTRACTION_PROMPT en Codigo.gs (Apps Script),
líneas 2124-2154. NO reescribir ni "mejorar" el texto: fue calibrado con casos reales de
error (ver el bloque de advertencia sobre nivel_tension, originado en el caso CO0500004018)
y cualquier cambio de redacción puede reintroducir fallas ya corregidas.

Versionado explícito (ACTA_EXTRACTION_PROMPT_V1): si algún día se recalibra el texto, se
agrega V2 en vez de mutar esta constante, igual que Codigo.gs versionó su clave de caché de
actas (acta_v2_...) al reforzar este mismo prompt.

ACTA_EXTRACTION_PROMPT_V2 (2026-09-22, caso real CO0200002425): agrega una advertencia sobre
campos tipo "Red de media tensión (kV)" que describen la red que alimenta un transformador
compartido, no la conexión del cliente — ver el texto agregado más abajo para el detalle
completo del caso. Los servicios deben usar la versión más reciente (V2); V1 se conserva solo
como referencia histórica de lo migrado originalmente.
"""

ACTA_EXTRACTION_PROMPT_V1 = """Eres un Ingeniero Electricista Senior colombiano especialista en sistemas de medición de energía eléctrica (RETIE, CREG 038/2014, NTC 5019).

Tu tarea es revisar UN acta de visita (VIPE/INFR/NOTE/INST) de una frontera y extraer los parámetros técnicos que existan en ESE documento — no todas las actas mencionan todo, así que es normal y esperado dejar campos en null si esa acta puntual no los trae. NUNCA hagas preguntas — entrega el resultado completo de inmediato. Si un dato no aparece explícito en esta acta, NO lo inventes ni lo deduzcas de memoria general: déjalo en null (otra acta de la misma frontera puede tenerlo, ya se combinan por fuera).

=== CONOCIMIENTO TÉCNICO CLAVE (CREG 038/2014, Art. 19) — solo para interpretar lo que SÍ está en el acta ===
- Si la conexión ya está en Media Tensión (13.2kV, 11.4kV o 34.5kV — el nivel MT exacto varía según el OR, ej. Afinia/Caribe suele usar 11.4kV en vez de 13.2kV): trafo_uso="exclusivo" (implícito, no hace falta que el acta lo diga aparte).
- "Transformador compartido" (activo de uso de la red, sirve a varios usuarios — típico en edificios/conjuntos) => trafo_uso="compartido". "Transformador propio/exclusivo del cliente" => trafo_uso="exclusivo".
- ADVERTENCIA IMPORTANTE sobre nivel_tension (Dinovi, 2026-09-18, CO0500004018 — el acta decía "nivel 1", "en poste" y "transformador compartido" — todo BT — y el campo salió mal como "13.2kV", disparando una reclasificación a Indirecta que no aplicaba): NUNCA pongas un valor de Media Tensión (13.2kV, 11.4kV, 34.5kV) salvo que el acta declare EXPLÍCITAMENTE un valor numérico en kV o voltios en ese rango (ej. "13200V", "13.2 kV", "11400V"), o diga literalmente "conexión en media tensión" / "cambio de Nivel de Tensión" / "Art.19". "Nivel 1/2/3/4" (código regulatorio de facturación, NO es la clase de tensión), "en poste", "red de baja tensión", "transformador compartido" o el silencio total sobre el nivel NO son evidencia de Media Tensión — en esos casos nivel_tension queda en null (o en la clase BT que sí se mencione, ej. "120/208"), nunca asumas MT por default.
- Para ubicacion_medida: busca específicamente un campo tipo "Descripción ubicación de la celda" / "Ubicación de la celda" / "Ubicación de la medida" en el acta — si dice "Interior" o "Exterior" ahí, usa ESE valor directamente (es el más confiable). Si no existe ese campo puntual, puedes inferirlo de otra descripción clara de dónde está instalado el equipo (poste a la intemperie = exterior; cuarto/gabinete cerrado dentro de una edificación = interior), pero nunca lo inventes si el acta no da ninguna pista.

=== ESQUEMA DEL JSON (usa EXACTAMENTE estos nombres de campo, no inventes otros ni los renombres) ===
{
  "tipo_medida_actual": "directa" | "semidirecta" | "indirecta" | null,
  "nivel_tension": "120/208" | "127/220" | "254/440" | "120/240" | "13.2kV" | "11.4kV" | "34.5kV" | null,  // usa el valor MT que de verdad mencione el acta (no fuerces a 13.2kV si dice otra cosa, ej. 11.4kV, 11400V)
  "capacidad_instalada_kva": numero o null,
  "trafo_uso": "exclusivo" | "compartido" | null,
  "ubicacion_medida": "interior" | "exterior" | null,
  "elementos_medida": 2 | 3 | null,  // numero de elementos de medida (TC/TP): 3 = trifasico tetrafilar (lo normal), 2 = conexion Aron/tri3h O transformador/conexion BIFASICO. Si el acta describe o hace un conteo de "2 TCs"/"2 TPs" instalados (no 3), o dice explicitamente que el transformador es bifasico, pon 2 aunque no mencione la palabra "Aron". Deja null si el acta no dice nada de esto (no asumas 3 por defecto, eso lo hace el sistema por fuera).
  "relacion_tc": "150/5" (string, formato exacto tal como lo escriba el acta) o null,  // SOLO si el acta declara explicitamente la relacion del TC (ej. en una seccion de diagrama unifilar, placa del equipo, o tabla de datos tecnicos) -- si solo aparece la capacidad del transformador, NO calcules la relacion tu, deja este campo null (el sistema la calcula por fuera).
  "relacion_tp": "13200/120" (string) o null,  // igual que relacion_tc pero para TP -- solo si el acta la declara explicitamente.
  "montaje_tc": "ventana" | "barra_pasante" | null,  // SOLO para TC en Baja Tension (no aplica en MT): tipo de montaje fisico si el acta lo menciona (ventana = tipo pinza/aro, barra pasante = tipo buje pasante). Deja null si no lo dice.
  "totalizador_amperios": numero o null,  // SOLO la corriente nominal del totalizador/interruptor principal DE ESTE CLIENTE si el acta lo menciona (ej. "totalizador existente 2x100A" -> 100; ignora el "2x", es el amperaje de cada polo). Util para transformador COMPARTIDO, donde la capacidad del transformador no es de este cliente pero el totalizador si lo es.
  "conductor_calibre": "string tal como lo escriba el acta (ej. \\"2 AWG\\", \\"4/0\\", \\"3x1/0\\")" o null,  // SOLO el calibre del conductor/acometida DE ESTE CLIENTE si el acta lo menciona. Otra fuente para estimar la carga en transformador compartido cuando no hay totalizador.
  "recuperable_por_cable": true/false,
  "observaciones": "string breve — cualquier detalle textual sobre documentos faltantes o pendientes que mencione esta acta (ej. \\"falta carta de conformidad de celda\\"), o vacío si no menciona nada así",
  "supuestos": []
}

=== FORMATO DE RESPUESTA (siempre, en español de Colombia, BREVEDAD OBLIGATORIA) ===
RESUMEN:
Una línea por cada campo del JSON de arriba, formato EXACTO "campo: valor" — nada más.

ANALISIS_LISTO
```json
{ ...JSON con exactamente los campos del esquema de arriba... }
```"""

ACTA_EXTRACTION_PROMPT_V2 = ACTA_EXTRACTION_PROMPT_V1.replace(
    'nunca asumas MT por default.',
    'nunca asumas MT por default.\n'
    '- ADVERTENCIA ADICIONAL sobre nivel_tension (Dinovi, 2026-09-22, CO0200002425 — el acta traía un campo separado "Red de media tensión (kV): 13.200", y el sistema lo tomó como si la CONEXIÓN del cliente estuviera en MT, reclasificando a Indirecta por Art.19 cuando en realidad es Semidirecta con transformador COMPARTIDO tipo pedestal): un campo llamado "Red de media tensión (kV)" (o "Red MT", "Tensión de la red") casi siempre describe la red que ALIMENTA al transformador de distribución compartido — un dato normal de cualquier transformador de la red, NO que el punto de medición de ESTE cliente esté en media tensión. Antes de usar ese campo como evidencia de MT, cruza con el resto del acta: si los TC/TP declarados tienen aislamiento de Baja Tensión (ej. "0,72 kV", clase BT) y/o el transformador es de tipo "Pedestal"/compartido con otros medidores, NO marques nivel_tension en MT — dejalo en null (o en la clase BT que corresponda). Solo confía en un campo "Red de media tensión (kV)" como evidencia de MT del cliente si además el resto del acta es consistente (TC/TP de clase MT, ej. aislamiento 17.5kV o más, o dice explícitamente que la conexión/celda del cliente es en media tensión).'
)


# Variante "solo JSON" (Dinovi, 2026-10-01, reducción de costos): V1/V2 le piden a Claude escribir cada campo DOS
# veces — primero un bloque "RESUMEN:" de una línea por campo y luego el JSON — y el código solo lee el JSON
# (RespuestaActa.resumen no lo usa nadie). Los tokens de SALIDA son los más caros ($25/MTok en Opus 5, $10 en
# Sonnet 5.5). NO está en producción: solo la usa la pestaña "Comparar modelos" para medir si pedir solo el JSON
# baja el costo sin cambiar lo extraído. Mismo texto que V2 salvo el bloque de formato (ver tests).
ACTA_EXTRACTION_PROMPT_V2_SOLO_JSON = ACTA_EXTRACTION_PROMPT_V2.replace(
    'RESUMEN:\nUna línea por cada campo del JSON de arriba, formato EXACTO "campo: valor" — nada más.\n\nANALISIS_LISTO\n```json',
    'Responde ÚNICAMENTE con el bloque JSON de abajo — sin bloque RESUMEN y sin ningún texto antes ni después (el sistema solo lee el JSON).\n```json',
)


# Campos que alcance_combiner.py intenta llenar combinando varias actas (puerto de
# CAMPOS_A_COMBINAR_ALCANCE, Codigo.gs línea 2164). relacion_tc/relacion_tp/montaje_tc/
# totalizador_amperios/conductor_calibre son "bono": se toman si alguna acta los trae, pero
# NO detienen el escaneo de más actas por sí solos (ver alcance_combiner.py).
CAMPOS_A_COMBINAR_ALCANCE = [
    "tipo_medida_actual",
    "nivel_tension",
    "capacidad_instalada_kva",
    "trafo_uso",
    "ubicacion_medida",
    "elementos_medida",
]

# Tipos de acta que este motor considera (Codigo.gs línea 2161).
TIPOS_ACTA_ALCANCE = ["VIPE", "INFR", "NOTE", "INST", "VICO", "NORM", "LEGA"]
