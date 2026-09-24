"""POST /api/lote_start — comparación masiva de CO contra "Data cambio NT"/
"Normalizaciones_Indirectas" (Dinovi, 2026-09-24). Recibe la lista de CO pegada, descarta en
silencio los que no estén en ninguna de las 2 hojas, y crea el lote — el análisis en sí corre
en pasos vía /api/lote_step (mismo patrón que actas_start.py/actas_step.py).

Body: {"cos": ["CO0100001344", "CO0800000348", ...]}
"""

from flask import Blueprint, jsonify, request

from core.services.lote_store import get_lote_store
from core.services.wiring import construir_dependencias

bp = Blueprint("lote_start", __name__)


@bp.post("/api/lote_start")
def lote_start():
    body = request.get_json(force=True, silent=True) or {}
    cos = body.get("cos")
    if not cos or not isinstance(cos, list):
        return jsonify({"error": '"cos" es obligatorio: una lista de códigos CO.'}), 400

    deps = construir_dependencias()
    resultado = get_lote_store(deps.sheets).crear_lote(cos)
    return jsonify(resultado)
