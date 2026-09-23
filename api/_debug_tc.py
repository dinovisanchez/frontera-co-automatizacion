"""TEMPORAL — inspeccionar catálogo real de TC (CO0100001344, Dinovi 2026-09-23). Borrar."""

from flask import Blueprint, jsonify

from core.services.catalogo_capex import obtener_catalogo_ref_capex
from core.services.wiring import construir_dependencias

bp = Blueprint("_debug_tc", __name__)


@bp.get("/api/_debug_tc")
def debug_tc():
    deps = construir_dependencias(requiere_metabase=False)
    catalogo = obtener_catalogo_ref_capex(deps.sheets)
    tcs = [i for i in catalogo if i["categoria"] == "Transformador de corriente"]
    return jsonify({
        "total": len(tcs),
        "items": [{"sku": i["sku"], "kv": i["tc"]["kv"], "ratio_range": i["tc"]["ratio_range"], "ubicacion": i["tc"]["ubicacion"], "burden": i["tc"]["burden"]} for i in tcs],
    })
