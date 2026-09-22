"""TEMPORAL — solo para diagnosticar por qué "factor_fx" sale null para un CO puntual.
Se borra después de confirmar el nombre real de la columna en BD_Telemedida.
"""

from flask import Blueprint, jsonify, request

from core.data_sources.sheets_client import SheetsClient
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo
from config.settings import CONTROL_SHEET_ID, MAESTRO_GID

bp = Blueprint("_debug_maestro", __name__)


@bp.get("/api/_debug_maestro")
def debug_maestro():
    co = normalizar_codigo(request.args.get("co") or "")
    deps = construir_dependencias(requiere_metabase=False)
    sheets: SheetsClient = deps.sheets
    hoja = sheets.hoja_externa_por_gid(CONTROL_SHEET_ID, MAESTRO_GID)
    if not hoja:
        return jsonify({"error": "no encontré la hoja maestra"}), 404
    datos = sheets.leer_todo(hoja, sin_formato=True)
    header = datos[0]
    fila = next((f for f in datos[1:] if f and normalizar_codigo(f[0]) == co), None)
    return jsonify({"header": header, "fila": fila})
