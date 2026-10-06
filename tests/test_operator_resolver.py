"""operator_resolver.py con Sheets/Metabase/LLM falsos (duck-typed) — sin credenciales reales.
"""

from unittest.mock import patch

from core.services.operator_resolver import (
    FUENTE_ACTA_PDF,
    FUENTE_HOJA_ORIGEN,
    FUENTE_PENDIENTE_MANUAL,
    resolver_operador_red,
)
from core.services import acta_downloader, operator_resolver


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


class CacheFalso:
    def __init__(self, guardado: dict | None = None):
        self.datos = dict(guardado or {})

    def obtener(self, url):
        return self.datos.get(url)

    def guardar(self, url, spec):
        self.datos[url] = spec


URL = "https://ejemplo.com/acta.pdf"
FILAS_METABASE = [{"service_type_id": "VIPE", "fecha_visita": "2026-01-01", "act_pdf_url": URL}]


def _resolver(monkeypatch, *, bytes_pdf=b"%PDF-fake-bytes", ocr=None, or_texto=None, or_pdf=None, drive_cfg=object(), cache=None):
    """Corre el resolver con la descarga, el OCR y los dos extractores simulados. Devuelve (resultado, llamadas, cache)."""
    from core.services import acta_ocr, operator_resolver as modulo

    llamadas, cache = [], cache or CacheFalso()
    monkeypatch.setattr(modulo, "get_acta_cache", lambda sheets: cache)
    monkeypatch.setattr(modulo.acta_downloader, "descargar_pdf_acta", lambda url: acta_downloader.ResultadoDescarga(ok=True, bytes_pdf=bytes_pdf))
    monkeypatch.setattr(modulo.acta_ocr, "ocr_texto_desde_bytes", lambda b, cfg: ocr or acta_ocr.OcrResultado(ok=False, motivo_fallo="sin OCR"))

    def desde_texto(texto, llm, co=None):
        llamadas.append("texto")
        return or_texto

    def desde_pdf(pdf, llm, co=None):
        llamadas.append("pdf")
        return or_pdf

    monkeypatch.setattr(modulo.or_extractor, "extraer_or_desde_texto", desde_texto)
    monkeypatch.setattr(modulo.or_extractor, "extraer_or_desde_pdf", desde_pdf)
    resultado = resolver_operador_red(SheetsClientFalso([]), MetabaseClientFalso(FILAS_METABASE), llm=object(), co_raw="CO0100002908", drive_cfg=drive_cfg)
    return resultado, llamadas, cache


def _ocr_ok():
    from core.services.acta_ocr import OcrResultado

    return OcrResultado(ok=True, texto="texto del acta " * 30)


def test_cae_a_leer_la_acta_si_no_esta_en_la_hoja(monkeypatch):
    resultado, llamadas, cache = _resolver(monkeypatch, ocr=_ocr_ok(), or_texto="EMCALI")

    assert resultado.fuente == FUENTE_ACTA_PDF and resultado.or_raw == "EMCALI"
    assert llamadas == ["texto"]  # el PDF entero (Opus, ≈ $0,26) NO se manda si el texto ya lo trajo
    assert cache.datos == {f"or::{URL}": {"or": "EMCALI"}}


def test_si_el_texto_no_trae_el_operador_se_prueba_el_pdf_cuando_cabe(monkeypatch):
    resultado, llamadas, _ = _resolver(monkeypatch, ocr=_ocr_ok(), or_texto=None, or_pdf="ENEL")

    assert resultado.or_raw == "ENEL" and llamadas == ["texto", "pdf"]


def test_si_el_ocr_falla_se_prueba_el_pdf_cuando_cabe(monkeypatch):
    resultado, llamadas, _ = _resolver(monkeypatch, ocr=None, or_pdf="ENEL")

    assert resultado.or_raw == "ENEL" and llamadas == ["pdf"]  # sin texto no se pregunta por texto


def test_un_pdf_demasiado_grande_para_la_api_nunca_se_manda_entero(monkeypatch):
    """Los PDF de más de ~22 MB daban HTTP 413: ahora ni se intentan por PDF (se queda lo que dé el texto)."""
    grande = b"%PDF" + b"0" * (operator_resolver.LIMITE_BYTES_PDF_COMPLETO + 1)

    resultado, llamadas, _ = _resolver(monkeypatch, bytes_pdf=grande, ocr=_ocr_ok(), or_texto=None, or_pdf="NO DEBE USARSE")

    assert llamadas == ["texto"] and resultado.fuente == FUENTE_PENDIENTE_MANUAL and resultado.or_raw is None


def test_un_pdf_grande_si_se_resuelve_por_el_texto(monkeypatch):
    grande = b"%PDF" + b"0" * (operator_resolver.LIMITE_BYTES_PDF_COMPLETO + 1)

    resultado, llamadas, _ = _resolver(monkeypatch, bytes_pdf=grande, ocr=_ocr_ok(), or_texto="AFINIA")

    assert resultado.or_raw == "AFINIA" and llamadas == ["texto"]


def test_sin_credenciales_de_drive_no_hay_ocr_y_se_usa_el_pdf_como_antes(monkeypatch):
    resultado, llamadas, _ = _resolver(monkeypatch, ocr=_ocr_ok(), or_pdf="EMCALI", drive_cfg=None)

    assert resultado.or_raw == "EMCALI" and llamadas == ["pdf"]


def test_si_el_operador_ya_esta_en_el_cache_no_se_descarga_ni_se_llama_a_claude(monkeypatch):
    cache = CacheFalso({f"or::{URL}": {"or": "ESSA"}})

    resultado, llamadas, _ = _resolver(monkeypatch, ocr=_ocr_ok(), or_texto="NO", or_pdf="NO", cache=cache)

    assert resultado.or_raw == "ESSA" and llamadas == []


def test_si_ningun_camino_lo_encuentra_queda_pendiente_manual_y_no_se_cachea(monkeypatch):
    resultado, llamadas, cache = _resolver(monkeypatch, ocr=_ocr_ok(), or_texto=None, or_pdf=None)

    assert resultado.fuente == FUENTE_PENDIENTE_MANUAL and cache.datos == {}


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
