"""GET /api/actas_status?co=... — progreso/resultado actual del job de un CO, sin avanzarlo.

Útil para que el frontend recupere el estado tras un refresh, o para que cron_reintentos.py
liste qué jobs siguen en_progreso.
"""

from flask import Blueprint, jsonify, request

from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("actas_status", __name__)


@bp.get("/api/actas_status")
def actas_status():
    co_raw = request.args.get("co")
    if not co_raw:
        return jsonify({"error": "El parámetro 'co' es obligatorio."}), 400
    co = normalizar_codigo(co_raw)

    deps = construir_dependencias(requiere_metabase=False)
    estado = deps.jobs.leer(co)
    if estado is None:
        return jsonify({"error": f'No hay ningún job para "{co}".'}), 404

    return jsonify({
        "co": co,
        "estado": estado.estado,
        "spec_combinado": estado.spec_combinado,
        "actas_pendientes": len(estado.actas_pendientes),
        "actas_usadas": estado.actas_usadas,
        "observaciones": estado.observaciones,
    })
