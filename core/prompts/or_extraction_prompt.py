"""System prompt para extraer SOLO el Operador de Red (OR) de una acta.

A diferencia de ACTA_EXTRACTION_PROMPT_V1 (14 campos, prompt original de Codigo.gs), este es
NUEVO — no existía en Codigo.gs porque el motor original nunca resolvía el OR desde el acta,
lo recibía ya resuelto desde el frontend (ver operator_resolver.py). Sigue el mismo patrón que
extraerRatioDeCertificadoCalibracion (Codigo.gs línea 3174-3205): una pregunta puntual, barata
(max_tokens bajo, effort "low"), en vez de correr la extracción completa de 14 campos solo
para este dato.
"""

OR_EXTRACTION_PROMPT_V1 = """Eres un ingeniero eléctrico colombiano. Te doy un acta de visita de una frontera de medición de energía eléctrica. Extrae SOLO el Operador de Red (OR) que aparezca explícitamente en el acta — el campo suele decir literalmente "OR:", "Operador de Red:" o el nombre de la empresa distribuidora (ej. "AFINIA", "EMCALI", "ENEL", "CELSIA VALLE", "ELECTROHUILA", "ESSA", "AIRE"). Si no aparece explícito en esta acta, responde null — no lo inventes ni lo asumas por la zona geográfica. Responde EXCLUSIVAMENTE un JSON, sin texto adicional: {"or": "AFINIA" (el texto tal cual aparece en el acta, o null si no aparece)}"""
