"""POST /api/guardar_opex — escribe la propuesta de mano de obra ya confirmada en la hoja
"OPEX", en la siguiente fila en blanco (nunca inserta fila — ver guardar_opex.py del core
sobre la tabla de referencia OR/Descargo/Acompañamiento que vive aparte, a la derecha).

Body: {"co": "CO0100002908", "operador": "EPM ANTIOQUIA", "filas": [{"maniobra": "...", "cantidad": 1}, ...]}
El costo lo calcula la propia hoja (fórmulas) — no se manda ni se escribe.
"""

from flask import Blueprint, jsonify, request

from core.services.guardar_opex import guardar_filas_opex
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("guardar_opex", __name__)


@bp.post("/api/guardar_opex")
def guardar_opex():
    body = request.get_json(force=True, silent=True) or {}
    co_raw = body.get("co")
    if not co_raw:
        return jsonify({"error": "El código CO es obligatorio."}), 400
    co = normalizar_codigo(co_raw)

    operador = body.get("operador") or ""
    filas_crudas = body.get("filas") or []
    filas = [f for f in filas_crudas if isinstance(f, dict) and f.get("maniobra")]
    if not filas:
        return jsonify({"error": "No hay ninguna fila con maniobra para guardar."}), 400

    deps = construir_dependencias(requiere_metabase=False)
    try:
        resultado = guardar_filas_opex(deps.sheets, co, operador, filas)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"guardadas": resultado["guardadas"], "hoja_url": resultado["hoja_url"]})
