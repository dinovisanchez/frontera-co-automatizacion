"""OPEX — regla del "Descargo" (columna I de la hoja "OPEX").

Cuando el alcance de un CO trae montaje de TCs o TPs — interior O exterior — la columna I lleva
un valor FIJO: $8.000.000 para todos los operadores (OR) salvo ENEL, que lleva $12.000.000
(Dinovi, 2026-09-30). Igual que el carro canasta (ver carro_canasta.py), va UNA sola vez por CO,
en la primera maniobra de montaje — el descargo es un solo corte del servicio por visita.

Mismo criterio de detección que el carro canasta: solo "Montaje TCs/TPs MT …", no el desmonte ni
las instalaciones que mencionan esas palabras solo para aclarar que NO las incluyen.
"""

from config.settings import DESCARGO_MONTAJE_TC_TP, DESCARGO_MONTAJE_TC_TP_ENEL
from core.services.carro_canasta import es_montaje_tc_tp
from core.services.tarifa_calculator import normalizar_operador_tarifario


def valor_descargo(operador: str | None) -> int:
    """Acepta el operador ya normalizado ("ENEL") o el texto crudo del OR (ej. "ENEL COLOMBIA")."""
    return DESCARGO_MONTAJE_TC_TP_ENEL if normalizar_operador_tarifario(operador) == "ENEL" else DESCARGO_MONTAJE_TC_TP


def indice_fila_descargo(maniobras: list[str | None]) -> int | None:
    """Índice de la ÚNICA fila que lleva el descargo (la primera de montaje de TCs/TPs), o None."""
    for i, maniobra in enumerate(maniobras):
        if es_montaje_tc_tp(maniobra):
            return i
    return None
