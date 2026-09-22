"""POST /api/analizar_alcance — orquestador final del CAPEX (puerto de
analizarAlcanceProvisional). NO lee actas por dentro: si `dictamen.sinActas` no vino en true,
exige que el job de /api/actas_start + /api/actas_step ya esté `completo` para este CO —
evita repetir el trabajo (y el riesgo de timeout) de leer actas en cada llamada.

Body: {"co": "...", "dictamen": {clasificacion, capacidadIncierta?, sinActas?,
seccionesForzadas?, detalleFaltante?}} — mismo JSON que ya arma Index.html en el original.
"""

from flask import Blueprint, jsonify, request

from core.services.alcance_provisional import analizar_alcance_provisional
from core.services.job_store import ESTADO_COMPLETO
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("analizar_alcance", __name__)


def _acta_resultado_desde_job(estado) -> dict | None:
    if not estado.actas_usadas:
        return None  # ninguna acta aportó nada -> equivalente a "sin acta" en el original
    ultima = estado.actas_usadas[0]

    def _distintos(vistos: list[dict]) -> list[dict] | None:
        vistos_unicos = []
        valores = set()
        for v in vistos:
            if v["valor"] not in valores:
                vistos_unicos.append(v)
                valores.add(v["valor"])
        return vistos_unicos if len(vistos_unicos) > 1 else None

    return {
        "spec": estado.spec_combinado, "observaciones": estado.observaciones, "actas": estado.actas_usadas,
        "acta_url": ultima["url"], "tipo_acta": ultima["tipo"], "fecha_acta": ultima["fecha"],
        "tiene_acta_instalacion": estado.tiene_acta_instalacion,
        "capacidades_encontradas": _distintos(estado.capacidades_vistas),
        "relaciones_tc_encontradas": _distintos(estado.relaciones_tc_vistas),
        "cortado_por_tiempo": False,  # ya no aplica: el diseño de "una acta por invocación" elimina ese riesgo
    }


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
        acta_resultado = _acta_resultado_desde_job(estado)

    resultado = analizar_alcance_provisional(deps.sheets, deps.llm, co, dictamen, acta_resultado, filas_metabase_co)
    return jsonify(resultado)
