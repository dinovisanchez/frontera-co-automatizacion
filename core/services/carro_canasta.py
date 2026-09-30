"""OPEX — regla del "Carro canasta" (columna H de la hoja "OPEX").

Cuando el alcance de un CO trae montaje de TCs o TPs en exterior, la columna H lleva un valor
FIJO ($4.500.000, ver CARRO_CANASTA_MONTAJE_EXTERIOR) — UNA sola vez por CO, en la primera
maniobra de montaje exterior, aunque haya montaje de TCs Y de TPs (Dinovi, 2026-09-30).

Solo cuenta "Montaje TCs/TPs MT … exterior". NO cuenta el desmonte, ni las instalaciones que
mencionan esas palabras solo para aclarar que NO las incluyen (ej. "Instalación indirecta
exterior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)") — por eso el nombre debe
EMPEZAR por "montaje", no solo contener las palabras.
"""

from core.services.tarifa_calculator import normalizar_texto_opex


def es_montaje_tc_tp_exterior(maniobra: str | None) -> bool:
    tokens = normalizar_texto_opex(maniobra).split(" ")
    return tokens[0] == "montaje" and "exterior" in tokens and ("tcs" in tokens or "tps" in tokens)


def indice_fila_carro_canasta(maniobras: list[str | None]) -> int | None:
    """Índice de la ÚNICA fila que lleva el carro canasta (la primera de montaje exterior de
    TCs/TPs), o None si el CO no tiene ninguna."""
    for i, maniobra in enumerate(maniobras):
        if es_montaje_tc_tp_exterior(maniobra):
            return i
    return None
