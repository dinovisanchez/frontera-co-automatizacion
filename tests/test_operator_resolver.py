"""operator_resolver.py con un SheetsClient falso (duck-typed) — sin credenciales reales de
Google ni llamadas a Metabase, como exige el encargo de migración.
"""

from core.services.operator_resolver import FUENTE_HOJA_ORIGEN, FUENTE_PENDIENTE_MANUAL, resolver_operador_red


class HojaFalsa:
    row_count = 10


class SheetsClientFalso:
    """Solo implementa lo que operator_resolver.py necesita: hoja_por_gid + leer_rango."""

    def __init__(self, filas_origen: list[list]):
        self._filas = filas_origen

    def hoja_por_gid(self, gid: int) -> HojaFalsa:
        return HojaFalsa()

    def leer_rango(self, hoja, fila_inicio, col_inicio, num_filas, num_cols):
        return self._filas


def test_resuelve_desde_hoja_origen_si_esta():
    filas = [["CO0100002908", "Cliente X", "AFINIA CARIBE_MAR", "Cambio de medidor", "", "", ""]]
    sheets = SheetsClientFalso(filas)

    resultado = resolver_operador_red(sheets, metabase_cfg=None, co_raw="co0100002908")

    assert resultado.fuente == FUENTE_HOJA_ORIGEN
    assert resultado.or_raw == "AFINIA CARIBE_MAR"


def test_queda_pendiente_manual_si_no_esta_en_ninguna_fuente():
    sheets = SheetsClientFalso(filas_origen=[])

    resultado = resolver_operador_red(sheets, metabase_cfg=None, co_raw="CO9999999999")

    assert resultado.fuente == FUENTE_PENDIENTE_MANUAL
    assert resultado.or_raw is None
    assert "revisión manual" in resultado.motivo


def test_normaliza_el_co_antes_de_comparar():
    filas = [["CO0100002908", "Cliente X", "ENEL", "Cambio de medidor", "", "", ""]]
    sheets = SheetsClientFalso(filas)

    resultado = resolver_operador_red(sheets, metabase_cfg=None, co_raw="  co 0100002908 ")

    assert resultado.co == "CO0100002908"
    assert resultado.or_raw == "ENEL"
