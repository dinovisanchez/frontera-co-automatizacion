"""POST /api/actas_start — crea (o reinicia) el job de actas de un CO y procesa la primera.

No procesa TODAS las actas de una sola vez a propósito (ver README, "Por qué una acta por
invocación"): el tamaño/latencia de cada acta es impredecible, así que cada invocación de
Vercel solo hace un paso. El frontend sigue llamando /api/actas_step hasta que
`completo: true`, o lo hace cron_reintentos.py si el frontend se desconecta.
"""

from flask import Blueprint, jsonify, request

from core.data_sources.llm_client import AnthropicRateLimitError
from core.services import alcance_combiner
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("actas_start", __name__)


@bp.post("/api/actas_start")
def actas_start():
    body = request.get_json(force=True, silent=True) or {}
    co_raw = body.get("co")
    if not co_raw:
        return jsonify({"error": "El código CO es obligatorio."}), 400
    co = normalizar_codigo(co_raw)

    deps = construir_dependencias()
    if deps.metabase is None:
        return jsonify({"error": "Metabase no está configurado (METABASE_URL/METABASE_API_KEY/METABASE_CARD_ID)."}), 500

    filas_metabase_co = deps.metabase.filas_por_co(co)
    if not filas_metabase_co:
        return jsonify({"error": f'No encontré filas de "{co}" en Metabase.'}), 404

    actas_pendientes = alcance_combiner.preparar_actas_pendientes(co, filas_metabase_co)
    if not actas_pendientes:
        return jsonify({"error": f'"{co}" no tiene ninguna acta VIPE/INFR/NOTE/INST/VICO/NORM/LEGA con act_pdf_url.'}), 404

    tiene_acta_instalacion = alcance_combiner.hay_acta_instalacion(filas_metabase_co)
    estado = deps.jobs.crear_o_reiniciar(co, actas_pendientes, tiene_acta_instalacion)
    try:
        resultado = alcance_combiner.procesar_siguiente_acta(estado, deps.llm, deps.drive_cfg, deps.sheets)
    except AnthropicRateLimitError as e:
        # Un 503/429 de Claude que sobrevivió los reintentos de llm_client.py es pasajero, no un
        # error real del CO (Dinovi, 2026-09-29: incidente real de Anthropic de ~35 min, "Claude
        # respondió HTTP 503" en casi cada llamada) — si lo marcáramos ESTADO_ERROR, el job queda
        # huérfano para siempre: cron_reintentos.py SOLO reintenta jobs en ESTADO_EN_PROGRESO, y
        # cada reintento manual del usuario volvía a chocar con lo mismo y a re-marcarlo error
        # (se veían 3-4 "Claude respondió HTTP 503" acumulados en observaciones del mismo job).
        # Dejamos el estado tal cual (en_progreso) para que el próximo /api/actas_step — del
        # frontend o del cron diario — reintente esta misma acta sin perder lo ya combinado.
        estado.observaciones.append(str(e))
        deps.jobs.guardar_progreso(estado)
        return jsonify({"error": str(e), "spec_combinado": estado.spec_combinado}), 503
    except Exception as e:  # noqa: BLE001 — mismo patrón que actas_step.py: sin esto, un error
        # real (no transitorio) tumbaba este endpoint con el error genérico de Flask en vez de
        # un JSON claro, Y el job recién creado nunca quedaba marcado como error.
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
