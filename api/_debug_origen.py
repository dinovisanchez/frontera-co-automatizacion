"""TEMPORAL — confirmar por qué "maniobra" sale vacío al guardar en Equipos. Se borra apenas
se confirme."""

from flask import Blueprint, jsonify, request

from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo
from config.settings import FILA_INICIO_HOJA_ORIGEN, GID_HOJA_ORIGEN

bp = Blueprint("_debug_origen", __name__)


@bp.get("/api/_debug_origen")
def debug_origen():
    co = normalizar_codigo(request.args.get("co") or "")
    deps = construir_dependencias(requiere_metabase=False)
    hoja = deps.sheets.hoja_por_gid(GID_HOJA_ORIGEN)
    datos = deps.sheets.leer_rango(hoja, FILA_INICIO_HOJA_ORIGEN, 1, hoja.row_count - FILA_INICIO_HOJA_ORIGEN + 1, 7)
    filas_co = [f for f in datos if normalizar_codigo(f[0]) == co]
    return jsonify({"encabezado_filas_1_a_3": deps.sheets.leer_rango(hoja, 1, 1, 3, 7), "filas_del_co": filas_co})
