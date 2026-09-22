"""POST /api/actas_start — crea (o reinicia) el job de actas de un CO y procesa la primera.

No procesa TODAS las actas de una sola vez a propósito (ver README, "Por qué una acta por
invocación"): el tamaño/latencia de cada acta es impredecible, así que cada invocación de
Vercel solo hace un paso. El frontend sigue llamando /api/actas_step hasta que
`completo: true`, o lo hace cron_reintentos.py si el frontend se desconecta.
"""

from flask import Flask, jsonify, request

from core.services import alcance_combiner
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

app = Flask(__name__)


@app.post("/api/actas_start")
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

    estado = deps.jobs.crear_o_reiniciar(co, actas_pendientes)
    resultado = alcance_combiner.procesar_siguiente_acta(estado, deps.llm, deps.drive_cfg)
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
