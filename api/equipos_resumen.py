"""GET /api/equipos_resumen — lista TODOS los CO ya guardados en la hoja "Equipos", agrupados,
con lo que se puede inferir para calcular su OPEX (pestaña "OPEX desde Equipos", Dinovi
2026-09-29). Una sola lectura de Sheets + regex en memoria — nada de actas ni LLM, corre muy por
debajo del límite de 60s de Vercel incluso con cientos de CO.
"""

from flask import Blueprint, jsonify

from core.services.equipos_resumen import listar_cos_en_equipos
from core.services.wiring import construir_dependencias

bp = Blueprint("equipos_resumen", __name__)


@bp.get("/api/equipos_resumen")
def equipos_resumen():
    deps = construir_dependencias(requiere_metabase=False)
    registros = listar_cos_en_equipos(deps.sheets)
    return jsonify({
        "cos": [
            {
                "co": r.co,
                "cliente": r.cliente,
                "or": r.or_,
                "maniobra": r.maniobra,
                "filas": r.filas,
                "tipoMedidaFinalInferido": r.tipo_medida_final_inferido,
                "ubicacionInferida": r.ubicacion_inferida,
                "secciones": r.secciones,
                "celdaSku": r.celda_sku,
                "filasCable": r.filas_cable,
                "filasOpexExistentes": r.filas_opex_existentes,
            }
            for r in registros
        ],
    })
