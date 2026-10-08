"""POST /api/guardar_opex — escribe la propuesta de mano de obra ya confirmada en la hoja
"OPEX", en la siguiente fila en blanco (nunca inserta fila — ver guardar_opex.py del core
sobre la tabla de referencia OR/Descargo/Acompañamiento que vive aparte, a la derecha).

Body: {"co": "CO0100002908", "operador": "EPM ANTIOQUIA", "filas": [{"maniobra": "...", "cantidad": 1}, ...]}
El costo lo calcula la propia hoja (fórmulas) — no se manda ni se escribe.
Única excepción, decidida por el backend a partir de las maniobras recibidas (el cliente no manda
esos valores), una sola vez por CO: columna H (Carro canasta) en la PRIMERA "Montaje TCs/TPs MT …
exterior", y columna I (Descargo) en la PRIMERA "Montaje TCs/TPs MT" (interior o exterior; el
valor depende del OR). La respuesta trae "carroCanasta" y "descargo": {"fila", "maniobra", "valor"} o null.

Desplazamiento (columna K, Dinovi 2026-10-08): la hoja pone el precio según la ciudad de la columna B; entre los
CO que se guardan juntos solo se deja UNO por ciudad. Como cada CO es una petición, el cliente manda las ciudades
que ya cobraron ("ciudades_con_desplazamiento", opcional) y recibe la lista actualizada en "ciudadesConDesplazamiento";
"desplazamiento" = {"ciudad", "aplicado", "fila", "alerta"} (o null si la hoja aún no tiene fórmula en K).
"""

from flask import Blueprint, jsonify, request

from core.services.guardar_opex import guardar_filas_opex
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("guardar_opex", __name__)


@bp.post("/api/guardar_opex")
def guardar_opex():
    body = request.get_json(force=True, silent=True) or {}
    co_raw = body.get("co")
    if not co_raw:
        return jsonify({"error": "El código CO es obligatorio."}), 400
    co = normalizar_codigo(co_raw)

    operador = body.get("operador") or ""
    filas_crudas = body.get("filas") or []
    filas = [f for f in filas_crudas if isinstance(f, dict) and f.get("maniobra")]
    if not filas:
        return jsonify({"error": "No hay ninguna fila con maniobra para guardar."}), 400

    ciudades = body.get("ciudades_con_desplazamiento")
    ciudades = [c for c in ciudades if isinstance(c, str)] if isinstance(ciudades, list) else []

    deps = construir_dependencias(requiere_metabase=False)
    try:
        resultado = guardar_filas_opex(deps.sheets, co, operador, filas, ciudades_con_desplazamiento=ciudades)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "guardadas": resultado["guardadas"], "hoja_url": resultado["hoja_url"],
        "carroCanasta": resultado["carro_canasta"], "descargo": resultado["descargo"],
        "desplazamiento": resultado["desplazamiento"], "ciudadesConDesplazamiento": resultado["ciudades_con_desplazamiento"],
    })
