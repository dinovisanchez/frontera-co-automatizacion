"""GET /api/lote_status?lote_id=... — resultado completo (todos los CO) del lote hasta ahora,
sin avanzarlo — para pintar/repintar la tabla de resultados de la comparación masiva.
"""

from flask import Blueprint, jsonify, request

from core.services.lote_store import get_lote_store
from core.services.wiring import construir_dependencias

bp = Blueprint("lote_status", __name__)


@bp.get("/api/lote_status")
def lote_status():
    lote_id = request.args.get("lote_id")
    if not lote_id:
        return jsonify({"error": '"lote_id" es obligatorio.'}), 400

    deps = construir_dependencias(requiere_metabase=False)
    filas = get_lote_store(deps.sheets).leer_lote(lote_id)
    return jsonify({"lote_id": lote_id, "filas": filas})
