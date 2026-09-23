"""POST /api/opex_resolver — resuelve operador + mano de obra de un CO a partir de lo que
CAPEX ya clasificó (tipo de medida final, ubicación, qué secciones cambian).

Body esperado:
{
  "co": "CO0100002908",
  "or_manual": "AFINIA",              # opcional: si no viene, se resuelve solo (ver operator_resolver.py)
  "tipo_medida_final": "indirecta",   # "directa" | "semidirecta" | "indirecta" — de clasificador_medida
  "ubicacion": "interior",            # "interior" | "exterior" | null — de spec.ubicacion_medida
  "secciones": {"medidor": true, "tc": true, "tp": true, "bloque_pruebas": true, "celda": false},
  "es_instalacion_nueva": false,      # true si no hay equipo previo que retirar/desmontar
  "filas_cable": [{"grupo": "Cable señal", "cantidad": 1}],  # opcional — cable no tiene maniobra propia, solo fuzzy-match
  "tipo_medida_actual": "directa"     # opcional — solo si hubo cambio de nivel de tensión (Art.19):
                                       # el retiro del medidor es del tipo ACTUAL, no del final
}

Por qué este contrato (no "filas_equipos" genérico como antes): se verificó la hoja real de
ref_tarifario y sus 72 maniobras están armadas por tipo de medida × ubicación, no por
categoría de equipo suelta — ver opex_desde_equipos.py.
"""

from flask import Blueprint, jsonify, request

from core.services.opex_desde_equipos import construir_opex_desde_equipos
from core.services.operator_resolver import FUENTE_PENDIENTE_MANUAL, resolver_operador_red
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("opex_resolver", __name__)

_TIPOS_MEDIDA_VALIDOS = {"directa", "semidirecta", "indirecta"}


@bp.post("/api/opex_resolver")
def opex_resolver():
    body = request.get_json(force=True, silent=True) or {}
    co_raw = body.get("co")
    if not co_raw:
        return jsonify({"error": "El código CO es obligatorio."}), 400
    co = normalizar_codigo(co_raw)

    tipo_medida_final = body.get("tipo_medida_final")
    if tipo_medida_final not in _TIPOS_MEDIDA_VALIDOS:
        return jsonify({"error": f'"tipo_medida_final" es obligatorio y debe ser uno de {sorted(_TIPOS_MEDIDA_VALIDOS)}.'}), 400

    secciones = body.get("secciones") or {}
    es_instalacion_nueva = bool(body.get("es_instalacion_nueva", False))
    ubicacion = body.get("ubicacion")
    filas_cable = body.get("filas_cable") or []
    tipo_medida_actual = body.get("tipo_medida_actual")

    deps = construir_dependencias(requiere_metabase=False)

    or_manual = body.get("or_manual")
    if or_manual:
        or_raw, fuente_or = or_manual, "manual"
    else:
        resultado_or = resolver_operador_red(deps.sheets, deps.metabase, deps.llm, co)
        if resultado_or.fuente == FUENTE_PENDIENTE_MANUAL:
            return jsonify({"co": co, "pendiente_operador": True, "motivo": resultado_or.motivo}), 202
        or_raw, fuente_or = resultado_or.or_raw, resultado_or.fuente

    resultado = construir_opex_desde_equipos(
        deps.sheets, co, or_raw, tipo_medida_final, ubicacion, secciones, es_instalacion_nueva, filas_cable,
        tipo_medida_actual=tipo_medida_actual,
    )

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
        "maniobrasDisponibles": resultado.maniobras_disponibles,
    })
