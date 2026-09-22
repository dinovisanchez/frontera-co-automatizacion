"""MetabaseClient con requests.post mockeado — nunca llama a una instancia real de Metabase."""

import pytest

from config.settings import MetabaseConfig
from core.data_sources import metabase_client as mc

_CSV_DE_PRUEBA = (
    "bia_code,contrato,service_type_id,fecha_visita,act_pdf_url\n"
    "CO0100002908,12345,VIPE,2026-01-01,https://ejemplo.com/acta1.pdf\n"
    "CO0999999999,99999,INST,2026-02-01,https://ejemplo.com/acta2.pdf\n"
)


class RespuestaFalsa:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_filas_por_co_filtra_client_side(monkeypatch):
    monkeypatch.setattr(mc.requests, "post", lambda *a, **k: RespuestaFalsa(200, _CSV_DE_PRUEBA))
    cliente = mc.MetabaseClient(MetabaseConfig(url="https://metabase.falso", api_key="x", card_id="82534"))

    filas = cliente.filas_por_co("CO0100002908")

    assert len(filas) == 1
    assert filas[0]["service_type_id"] == "VIPE"


def test_401_lanza_error_de_autenticacion_no_operador_no_determinado(monkeypatch):
    monkeypatch.setattr(mc.requests, "post", lambda *a, **k: RespuestaFalsa(401, "unauthorized"))
    cliente = mc.MetabaseClient(MetabaseConfig(url="https://metabase.falso", api_key="mala", card_id="82534"))

    with pytest.raises(mc.MetabaseAuthError):
        cliente.filas_por_co("CO0100002908")


def test_429_lanza_rate_limit_error(monkeypatch):
    monkeypatch.setattr(mc.requests, "post", lambda *a, **k: RespuestaFalsa(429, "rate limited"))
    cliente = mc.MetabaseClient(MetabaseConfig(url="https://metabase.falso", api_key="x", card_id="82534"))

    with pytest.raises(mc.MetabaseRateLimitError):
        cliente.filas_por_co("CO0100002908")


def test_csv_se_cachea_entre_llamadas(monkeypatch):
    llamadas = {"n": 0}

    def post_falso(*a, **k):
        llamadas["n"] += 1
        return RespuestaFalsa(200, _CSV_DE_PRUEBA)

    monkeypatch.setattr(mc.requests, "post", post_falso)
    cliente = mc.MetabaseClient(MetabaseConfig(url="https://metabase.falso", api_key="x", card_id="82534"))

    cliente.filas_por_co("CO0100002908")
    cliente.filas_por_co("CO0999999999")

    assert llamadas["n"] == 1  # el segundo filas_por_co reutilizó el CSV cacheado
