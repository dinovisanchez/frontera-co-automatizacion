"""POST /api/lote_step — avanza UN paso del lote (una acta de un CO, o el análisis final de ese
CO cuando ya no le faltan actas). El frontend hace polling en un loop corto hasta que la
respuesta traiga `completo_lote: true` — mismo patrón que /api/actas_step.

Body: {"lote_id": "..."}
"""

from flask import Blueprint, jsonify, request

from core.services.lote_store import get_lote_store
from core.services.wiring import construir_dependencias

bp = Blueprint("lote_step", __name__)


@bp.post("/api/lote_step")
def lote_step():
    body = request.get_json(force=True, silent=True) or {}
    lote_id = body.get("lote_id")
    if not lote_id:
        return jsonify({"error": '"lote_id" es obligatorio.'}), 400

    deps = construir_dependencias()
    resultado = get_lote_store(deps.sheets).siguiente_paso(deps.llm, deps.drive_cfg, deps.metabase, lote_id)
    return jsonify(resultado)
