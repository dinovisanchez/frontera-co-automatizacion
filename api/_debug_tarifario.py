"""TEMPORAL — listar maniobras de ref_tarifario que mencionan "gabinete"/"directa"/"celda"
para revisar si hay una maniobra de instalación de gabinete que no se esté usando."""

from flask import Blueprint, jsonify

from core.services import tarifa_calculator as tc
from core.services.wiring import construir_dependencias

bp = Blueprint("_debug_tarifario", __name__)


@bp.get("/api/_debug_tarifario")
def debug_tarifario():
    deps = construir_dependencias(requiere_metabase=False)
    tarifario = tc.obtener_ref_tarifario_cacheado(deps.sheets)
    maniobras = tarifario["maniobras"]
    filtradas = [m for m in maniobras if any(p in m.lower() for p in ["gabinete", "directa", "celda", "policarbonato"])]
    return jsonify({"total_maniobras": len(maniobras), "coinciden": filtradas})
