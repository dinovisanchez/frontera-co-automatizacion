"""Parseo y validación de la respuesta del LLM para UN acta — puerto de parseRespuestaAlcance
(Codigo.gs línea 3601) más un validador de esquema explícito (nuevo: el original confiaba en
que el JSON ya viniera bien formado).

Regla de oro (no negociable, ver ALCANCE_EXTRACTION_PROMPT): un campo ausente en el JSON del
LLM se normaliza a None, NUNCA se rellena con un valor por defecto inventado.
"""

import json
import re
from dataclasses import dataclass

_PATRON_JSON = re.compile(r"\{[\s\S]*\}")

# Los 14 campos del esquema (ver acta_extraction_prompt.py) — cualquier campo que el LLM no
# incluya queda en None al validar, igual que si el acta no lo hubiera mencionado.
CAMPOS_ESQUEMA_ACTA = (
    "tipo_medida_actual",
    "nivel_tension",
    "capacidad_instalada_kva",
    "trafo_uso",
    "ubicacion_medida",
    "elementos_medida",
    "relacion_tc",
    "relacion_tp",
    "montaje_tc",
    "totalizador_amperios",
    "conductor_calibre",
    "recuperable_por_cable",
    "observaciones",
    "supuestos",
)


@dataclass
class RespuestaActa:
    resumen: str
    spec: dict | None  # None si el LLM no devolvió JSON parseable — el llamador decide qué hacer


def parsear_respuesta_alcance(texto: str) -> RespuestaActa:
    """Puerto 1:1 de parseRespuestaAlcance: separa el bloque RESUMEN del JSON final."""
    idx_resumen = texto.find("RESUMEN:")
    idx_listo = texto.find("ANALISIS_LISTO")

    resumen = ""
    if idx_resumen != -1:
        fin = idx_listo if idx_listo != -1 else len(texto)
        resumen = texto[idx_resumen + len("RESUMEN:") : fin].strip()

    spec = None
    match = _PATRON_JSON.search(texto)
    if match:
        try:
            spec = json.loads(match.group(0))
        except json.JSONDecodeError:
            spec = None  # spec queda None si no parsea — igual que el original

    return RespuestaActa(resumen=resumen, spec=spec)


def normalizar_spec_acta(spec_crudo: dict) -> dict:
    """Fuerza el spec a tener EXACTAMENTE las 14 llaves del esquema, sin inventar valores:
    cualquier campo ausente en la respuesta del LLM queda en None (o [] para supuestos).
    """
    normalizado = {}
    for campo in CAMPOS_ESQUEMA_ACTA:
        if campo == "supuestos":
            normalizado[campo] = spec_crudo.get(campo) or []
        else:
            normalizado[campo] = spec_crudo.get(campo, None)
    return normalizado
