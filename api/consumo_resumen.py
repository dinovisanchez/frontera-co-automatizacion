"""GET /api/consumo_resumen[?desde=YYYY-MM-DD] — resumen del consumo de la API de Claude a partir de
la pestaña "PyConsumo" (una fila por llamada, ver core/services/consumo.py). Solo lee la hoja: no
llama a Claude ni cuesta nada. `desde` (UTC) acota el periodo, útil para comparar "antes" y "después"
de un cambio de modelo/esfuerzo. Aun así cada fila trae su modelo y esfuerzo, y el resumen incluye
`por_configuracion`, así que el antes/después también se puede leer sin fechas.
"""

import re

from flask import Blueprint, jsonify, request

from core.services.consumo import get_consumo_store, resumir
from core.services.wiring import construir_dependencias

bp = Blueprint("consumo_resumen", __name__)


@bp.get("/api/consumo_resumen")
def consumo_resumen():
    desde = (request.args.get("desde") or "").strip() or None
    if desde and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", desde):
        return jsonify({"error": '"desde" debe tener el formato AAAA-MM-DD.'}), 400

    deps = construir_dependencias(requiere_metabase=False)
    try:
        registros = get_consumo_store(deps.sheets).leer(desde=desde)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(resumir(registros))
