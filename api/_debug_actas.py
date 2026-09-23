"""TEMPORAL — diagnosticar por qué faltan actas en un CO puntual (Dinovi, 2026-09-23,
CO0100000215: "en esta faltó una infr"). Borrar después de usar."""

from flask import Blueprint, jsonify, request

from core.services.alcance_combiner import TIPOS_ACTA_ALCANCE, preparar_actas_pendientes
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("_debug_actas", __name__)


@bp.get("/api/_debug_actas")
def debug_actas():
    co_raw = request.args.get("co")
    if not co_raw:
        return jsonify({"error": "co requerido"}), 400
    co = normalizar_codigo(co_raw)
    deps = construir_dependencias()
    filas = deps.metabase.filas_por_co(co)
    todas = [
        {
            "service_type_id": r.get("service_type_id"),
            "fecha_visita": r.get("fecha_visita"),
            "act_pdf_url": r.get("act_pdf_url"),
            "calificaba_tipo": (r.get("service_type_id") or "").upper() in TIPOS_ACTA_ALCANCE,
            "tiene_pdf_url": bool(r.get("act_pdf_url")),
        }
        for r in filas
    ]
    seleccionadas = preparar_actas_pendientes(co, filas)
    return jsonify({
        "co": co,
        "total_filas_metabase": len(filas),
        "tipos_alcance_validos": TIPOS_ACTA_ALCANCE,
        "todas": todas,
        "seleccionadas_para_leer": [{"service_type_id": r.get("service_type_id"), "fecha_visita": r.get("fecha_visita"), "act_pdf_url": r.get("act_pdf_url")} for r in seleccionadas],
    })
