"""GET /api/cron_reintentos — invocado por Vercel Cron (ver vercel.json).

Red de seguridad para jobs que quedaron "en_progreso" sin que nadie siga llamando a
/api/actas_step (ej. el usuario cerró la pestaña a medio análisis) — avanza UN paso de cada
job pendiente en cada tick del cron, para que eventualmente todos terminen solos.
"""

from flask import Blueprint, jsonify

from core.services import alcance_combiner
from core.services.job_store import ESTADO_EN_PROGRESO
from core.services.wiring import construir_dependencias

bp = Blueprint("cron_reintentos", __name__)

MAX_JOBS_POR_TICK = 10  # límite de costo/tiempo por invocación del cron, no de corrección


@bp.get("/api/cron_reintentos")
def cron_reintentos():
    deps = construir_dependencias(requiere_metabase=False)
    cos_pendientes = deps.jobs.listar_cos_por_estado(ESTADO_EN_PROGRESO)[:MAX_JOBS_POR_TICK]

    avanzados = []
    for co in cos_pendientes:
        estado = deps.jobs.leer(co)
        if estado is None:
            continue
        try:
            resultado = alcance_combiner.procesar_siguiente_acta(estado, deps.llm, deps.drive_cfg, deps.sheets)
        except Exception as e:  # noqa: BLE001 — un job con error no debe tumbar el resto del tick
            deps.jobs.marcar_error(estado, str(e))
            avanzados.append({"co": co, "error": str(e)})
            continue

        if resultado.completo:
            deps.jobs.marcar_completo(resultado.estado)
        else:
            deps.jobs.guardar_progreso(resultado.estado)
        avanzados.append({"co": co, "completo": resultado.completo})

    return jsonify({"jobs_procesados": len(avanzados), "detalle": avanzados})
