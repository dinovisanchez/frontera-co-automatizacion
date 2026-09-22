"""TEMPORAL — solo para confirmar las columnas reales de la hoja "OPEX" antes de escribir en
producción. Se borra apenas se confirme el layout exacto.
"""

from flask import Blueprint, jsonify

from core.services.wiring import construir_dependencias
from config.settings import SHEET_OPEX

bp = Blueprint("_debug_opex", __name__)


@bp.get("/api/_debug_opex")
def debug_opex():
    deps = construir_dependencias(requiere_metabase=False)
    hoja = deps.sheets.hoja_por_nombre(SHEET_OPEX)
    datos = hoja.get_values()[:5]
    return jsonify({"filas": datos, "total_filas_con_grid": hoja.row_count})
