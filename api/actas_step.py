"""POST /api/actas_step — procesa UNA acta más del job ya creado por /api/actas_start.

El frontend hace polling: llama esto en un loop corto hasta que la respuesta traiga
`completo: true`. Cada llamada es rápida (una sola acta, un máximo de 2 llamadas al LLM),
muy por debajo de cualquier maxDuration razonable de Vercel.
"""

from flask import Blueprint, jsonify, request

from core.services import alcance_combiner
from core.services.job_store import ESTADO_COMPLETO
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("actas_step", __name__)


@bp.post("/api/actas_step")
def actas_step():
    body = request.get_json(force=True, silent=True) or {}
    co_raw = body.get("co")
    if not co_raw:
        return jsonify({"error": "El código CO es obligatorio."}), 400
    co = normalizar_codigo(co_raw)

    deps = construir_dependencias(requiere_metabase=False)
    estado = deps.jobs.leer(co)
    if estado is None:
        return jsonify({"error": f'No hay un job de actas para "{co}" — llama primero a /api/actas_start.'}), 404
    if estado.estado == ESTADO_COMPLETO:
        return jsonify({"co": co, "completo": True, "spec_combinado": estado.spec_combinado, "actas_usadas": estado.actas_usadas, "observaciones": estado.observaciones})

    try:
        resultado = alcance_combiner.procesar_siguiente_acta(estado, deps.llm, deps.drive_cfg)
    except Exception as e:  # noqa: BLE001 — se guarda el error en el job en vez de perder el progreso ya combinado
        deps.jobs.marcar_error(estado, str(e))
        return jsonify({"error": str(e), "spec_combinado": estado.spec_combinado}), 500

    if resultado.completo:
        deps.jobs.marcar_completo(resultado.estado)
    else:
        deps.jobs.guardar_progreso(resultado.estado)

    return jsonify({
        "co": co,
        "completo": resultado.completo,
        "spec_combinado": resultado.estado.spec_combinado,
        "actas_pendientes": len(resultado.estado.actas_pendientes),
        "actas_usadas": resultado.estado.actas_usadas,
        "observaciones": resultado.estado.observaciones,
    })
