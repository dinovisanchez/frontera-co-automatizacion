"""POST /api/guardar_opex — escribe la propuesta de mano de obra ya confirmada en la hoja
"OPEX" (al final — esa hoja no tiene columna de código CO para ubicar una posición puntual).

Body: {"filas": [{"maniobra": "...", "cantidad": 1, "costo_unitario": 640458, "costo_total": 640458}, ...]}
"""

from flask import Blueprint, jsonify, request

from core.services.guardar_opex import guardar_filas_opex
from core.services.wiring import construir_dependencias

bp = Blueprint("guardar_opex", __name__)


@bp.post("/api/guardar_opex")
def guardar_opex():
    body = request.get_json(force=True, silent=True) or {}
    filas_crudas = body.get("filas") or []
    filas = [f for f in filas_crudas if isinstance(f, dict) and f.get("maniobra")]
    if not filas:
        return jsonify({"error": "No hay ninguna fila con maniobra para guardar."}), 400

    deps = construir_dependencias(requiere_metabase=False)
    try:
        resultado = guardar_filas_opex(deps.sheets, filas)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"guardadas": resultado["guardadas"], "hoja_url": resultado["hoja_url"]})
