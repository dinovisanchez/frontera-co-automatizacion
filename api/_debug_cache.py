"""TEMPORAL — verificar que acta_cache.py realmente está guardando/leyendo. Borrar después."""

from flask import Blueprint, jsonify, request

from core.services.acta_cache import get_acta_cache
from core.services.wiring import construir_dependencias

bp = Blueprint("_debug_cache", __name__)


@bp.get("/api/_debug_cache")
def debug_cache():
    url = request.args.get("url")
    deps = construir_dependencias(requiere_metabase=False)
    hoja = deps.sheets.hoja_por_nombre("PyActasCache") if True else None
    try:
        hoja = deps.sheets.hoja_por_nombre("PyActasCache")
        valores = hoja.get_all_values()
    except Exception as e:
        return jsonify({"error": f"no existe la hoja o falló: {e}"})
    cache = get_acta_cache(deps.sheets)
    return jsonify({
        "total_filas": len(valores) - 1,
        "urls_en_cache": [f[0] for f in valores[1:]],
        "resultado_para_url": cache.obtener(url) if url else None,
    })
