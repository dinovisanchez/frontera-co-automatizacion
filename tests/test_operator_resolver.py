"""operator_resolver.py con Sheets/Metabase/LLM falsos (duck-typed) — sin credenciales reales.
"""

from unittest.mock import patch

from core.services.operator_resolver import (
    FUENTE_ACTA_PDF,
    FUENTE_HOJA_ORIGEN,
    FUENTE_PENDIENTE_MANUAL,
    resolver_operador_red,
)
from core.services import acta_downloader


class HojaFalsa:
    row_count = 10


class SheetsClientFalso:
    def __init__(self, filas_origen: list[list]):
        self._filas = filas_origen

    def hoja_por_gid(self, gid: int) -> HojaFalsa:
        return HojaFalsa()

    def leer_rango(self, hoja, fila_inicio, col_inicio, num_filas, num_cols):
        return self._filas


class MetabaseClientFalso:
    def __init__(self, filas: list[dict]):
        self._filas = filas

    def filas_por_co(self, co: str) -> list[dict]:
        return self._filas


def test_resuelve_desde_hoja_origen_si_esta():
    sheets = SheetsClientFalso([["CO0100002908", "Cliente X", "AFINIA CARIBE_MAR", "Cambio de medidor", "", "", ""]])

    resultado = resolver_operador_red(sheets, metabase=None, llm=None, co_raw="co0100002908")

    assert resultado.fuente == FUENTE_HOJA_ORIGEN
    assert resultado.or_raw == "AFINIA CARIBE_MAR"


def test_cae_a_leer_la_acta_pdf_si_no_esta_en_la_hoja():
    sheets = SheetsClientFalso(filas_origen=[])
    metabase = MetabaseClientFalso([
        {"service_type_id": "VIPE", "fecha_visita": "2026-01-01", "act_pdf_url": "https://ejemplo.com/acta.pdf"},
    ])

    descarga_falsa = acta_downloader.ResultadoDescarga(ok=True, bytes_pdf=b"%PDF-fake-bytes")
    with patch("core.services.operator_resolver.acta_downloader.descargar_pdf_acta", return_value=descarga_falsa), \
         patch("core.services.operator_resolver.or_extractor.extraer_or_desde_pdf", return_value="EMCALI"):
        resultado = resolver_operador_red(sheets, metabase, llm=object(), co_raw="CO0100002908")

    assert resultado.fuente == FUENTE_ACTA_PDF
    assert resultado.or_raw == "EMCALI"


def test_queda_pendiente_manual_si_no_hay_ninguna_fuente():
    sheets = SheetsClientFalso(filas_origen=[])

    resultado = resolver_operador_red(sheets, metabase=None, llm=None, co_raw="CO9999999999")

    assert resultado.fuente == FUENTE_PENDIENTE_MANUAL
    assert resultado.or_raw is None


def test_normaliza_el_co_antes_de_comparar():
    sheets = SheetsClientFalso([["CO0100002908", "Cliente X", "ENEL", "Cambio de medidor", "", "", ""]])

    resultado = resolver_operador_red(sheets, metabase=None, llm=None, co_raw="  co 0100002908 ")

    assert resultado.co == "CO0100002908"
    assert resultado.or_raw == "ENEL"
