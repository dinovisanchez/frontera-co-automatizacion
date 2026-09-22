"""POST /api/opex_resolver — resuelve operador + mano de obra de un CO desde su alcance de
equipos ya calculado (CAPEX).

Normalmente es rápido (solo lee la hoja "Data" + hace fuzzy-match de texto), pero si el CO no
tiene OR en esa hoja, cae a leer el acta más reciente (descarga PDF + 1 llamada puntual y
barata al LLM, ver operator_resolver.py/or_extractor.py) — ese caso sí puede tardar unos
segundos, cubierto por el `maxDuration: 30` de vercel.json.

Body esperado: {co, or_manual?, equipos_actuales, filas_equipos}. `or_manual` permite que el
frontend mande el operador a mano cuando resolver_operador_red devuelve "pendiente_manual"
(el CO no tiene OR en "Data" ni se pudo leer de ninguna acta).
"""

from flask import Flask, jsonify, request

from core.services.opex_desde_equipos import construir_opex_desde_equipos
from core.services.operator_resolver import FUENTE_PENDIENTE_MANUAL, resolver_operador_red
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

app = Flask(__name__)


@app.post("/api/opex_resolver")
def opex_resolver():
    body = request.get_json(force=True, silent=True) or {}
    co_raw = body.get("co")
    if not co_raw:
        return jsonify({"error": "El código CO es obligatorio."}), 400
    co = normalizar_codigo(co_raw)

    filas_equipos = body.get("filas_equipos") or []
    if not filas_equipos:
        return jsonify({"error": "Se necesita 'filas_equipos' (el alcance de equipos de CAPEX) para derivar OPEX."}), 400
    equipos_actuales = body.get("equipos_actuales") or {}

    deps = construir_dependencias(requiere_metabase=False)

    or_manual = body.get("or_manual")
    if or_manual:
        or_raw, fuente_or = or_manual, "manual"
    else:
        resultado_or = resolver_operador_red(deps.sheets, deps.metabase, deps.llm, co)
        if resultado_or.fuente == FUENTE_PENDIENTE_MANUAL:
            return jsonify({"co": co, "pendiente_operador": True, "motivo": resultado_or.motivo}), 202
        or_raw, fuente_or = resultado_or.or_raw, resultado_or.fuente

    resultado = construir_opex_desde_equipos(deps.sheets, co, or_raw, equipos_actuales, filas_equipos)

    return jsonify({
        "co": resultado.co,
        "operador": resultado.operador,
        "orOriginal": resultado.or_original,
        "fuenteOperador": fuente_or,
        "opcionCumplimiento": resultado.opcion_cumplimiento,
        "filas": resultado.filas,
        "totalGeneral": resultado.total_general,
        "derivadoDeEquipos": resultado.derivado_de_equipos,
        "nota": resultado.nota,
        "alertas": resultado.alertas,
    })
