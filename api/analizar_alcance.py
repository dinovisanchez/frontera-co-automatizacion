"""POST /api/analizar_alcance — orquestador final del CAPEX (puerto de
analizarAlcanceProvisional). NO lee actas por dentro: si `dictamen.sinActas` no vino en true,
exige que el job de /api/actas_start + /api/actas_step ya esté `completo` para este CO —
evita repetir el trabajo (y el riesgo de timeout) de leer actas en cada llamada.

Body: {"co": "...", "dictamen": {clasificacion, capacidadIncierta?, sinActas?,
seccionesForzadas?, detalleFaltante?}} — mismo JSON que ya arma Index.html en el original.
"""

from flask import Blueprint, jsonify, request

from core.services.alcance_combiner import acta_resultado_desde_estado
from core.services.alcance_provisional import analizar_alcance_provisional
from core.services.job_store import ESTADO_COMPLETO
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("analizar_alcance", __name__)


@bp.post("/api/analizar_alcance")
def analizar_alcance():
    body = request.get_json(force=True, silent=True) or {}
    co_raw = body.get("co")
    if not co_raw:
        return jsonify({"error": "El código CO es obligatorio."}), 400
    co = normalizar_codigo(co_raw)
    dictamen = body.get("dictamen") or {}
    if dictamen.get("clasificacion") not in ("cumple", "recuperable", "normalizacion"):
        return jsonify({"error": '"dictamen.clasificacion" es obligatorio: "cumple" | "recuperable" | "normalizacion".'}), 400

    deps = construir_dependencias()
    if deps.metabase is None:
        return jsonify({"error": "Metabase no está configurado (METABASE_URL/METABASE_API_KEY/METABASE_CARD_ID)."}), 500
    filas_metabase_co = deps.metabase.filas_por_co(co)

    acta_resultado = None
    if not dictamen.get("sinActas"):
        estado = deps.jobs.leer(co)
        if estado is None:
            return jsonify({"error": f'No hay actas analizadas para "{co}" — llama primero a /api/actas_start (o marca dictamen.sinActas=true si de verdad no quieres leer actas).'}), 409
        if estado.estado != ESTADO_COMPLETO:
            return jsonify({"error": f'El análisis de actas de "{co}" todavía no terminó (estado: {estado.estado}) — sigue llamando a /api/actas_step hasta completo:true.'}), 409
        acta_resultado = acta_resultado_desde_estado(estado)

    resultado = analizar_alcance_provisional(deps.sheets, deps.llm, co, dictamen, acta_resultado, filas_metabase_co)
    return jsonify(resultado)
