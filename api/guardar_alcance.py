"""POST /api/guardar_alcance — escribe la propuesta ya confirmada en la hoja "Equipos"
(equivalente a guardarAlcanceProvisional del Apps Script). Solo se llama cuando el usuario
le da "Confirmado" en el frontend — nada se guarda solo.

Body: {"co": "...", "filas": [{"sku": "...", "cantidad": 1, "tipo": "..."}, ...], "maniobra_respaldo": "Normalización"}
"maniobra_respaldo" (opcional): texto a usar en la columna "Maniobra" cuando la hoja "Data"
no trae nada ahí para este CO (pasa seguido) — típicamente la clasificación elegida.
"""

from flask import Blueprint, jsonify, request

from core.services.guardar_equipos import guardar_filas_equipos
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("guardar_alcance", __name__)


@bp.post("/api/guardar_alcance")
def guardar_alcance():
    body = request.get_json(force=True, silent=True) or {}
    co_raw = body.get("co")
    if not co_raw:
        return jsonify({"error": "El código CO es obligatorio."}), 400
    co = normalizar_codigo(co_raw)

    filas_crudas = body.get("filas") or []
    filas = [f for f in filas_crudas if isinstance(f, dict) and f.get("sku")]
    if not filas:
        return jsonify({"error": "No hay ninguna fila con SKU para guardar."}), 400

    maniobra_respaldo = body.get("maniobra_respaldo") or None

    deps = construir_dependencias(requiere_metabase=False)
    try:
        resultado = guardar_filas_equipos(deps.sheets, co, filas, maniobra_respaldo=maniobra_respaldo)
    except RuntimeError as e:
        # ej. no existe la hoja "Equipos", o falta la fila de origen en "Data"
        return jsonify({"error": str(e)}), 500

    return jsonify({"co": co, "guardadas": resultado["guardadas"], "hoja_url": resultado["hoja_url"]})
