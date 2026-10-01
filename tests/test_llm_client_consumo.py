"""Registro de consumo en AnthropicClient.enviar — con requests.post simulado, sin llamar a Anthropic."""

import pytest
import requests

from config.settings import AnthropicConfig
from core.data_sources import llm_client
from core.data_sources.llm_client import AnthropicClient, AnthropicRateLimitError, contexto_llamada

BODY_TEXTO = {
    "model": "claude-opus-5", "max_tokens": 2000, "output_config": {"effort": "medium"},
    "system": [{"type": "text", "text": "prompt"}],
    "messages": [{"role": "user", "content": [{"type": "text", "text": "hola"}]}],
}
BODY_PDF = {**BODY_TEXTO, "messages": [{"role": "user", "content": [{"type": "document", "source": {}}, {"type": "text", "text": "x"}]}]}


class Resp:
    def __init__(self, status=200, data=None, text="", headers=None):
        self.status_code, self._data, self.text, self.headers = status, data or {}, text, headers or {}

    def json(self):
        return self._data


def _ok(uso=None, stop="end_turn"):
    return Resp(200, {
        "content": [{"type": "text", "text": "{}"}], "stop_reason": stop,
        "usage": uso or {"input_tokens": 300, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 2500,
                         "output_tokens": 900, "output_tokens_details": {"thinking_tokens": 700}},
    }, headers={"request-id": "req_123"})


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    c = AnthropicClient(AnthropicConfig(api_key="fake"))
    c.registros = []
    c.registrador = c.registros.append
    return c


def _postear(monkeypatch, *respuestas):
    cola = list(respuestas)

    def falso(*a, **k):
        r = cola.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(llm_client.requests, "post", falso)


def test_registra_los_tokens_de_una_llamada_exitosa(cliente, monkeypatch):
    _postear(monkeypatch, _ok())

    assert cliente.enviar(BODY_TEXTO) == "{}"

    (r,) = cliente.registros
    assert (r["entrada"], r["escritura_cache"], r["lectura_cache"], r["salida"], r["razonamiento"]) == (300, 0, 2500, 900, 700)
    assert r["modelo"] == "claude-opus-5" and r["esfuerzo"] == "medium"
    assert r["resultado"] == "ok" and r["stop_reason"] == "end_turn" and r["request_id"] == "req_123"
    assert r["intentos"] == 1 and r["fallidos"] == 0
    assert r["tipo"] == "texto" and r["origen"] == "individual"


def test_el_tipo_se_infiere_del_body_si_nadie_lo_etiqueta(cliente, monkeypatch):
    _postear(monkeypatch, _ok())
    cliente.enviar(BODY_PDF)
    assert cliente.registros[0]["tipo"] == "pdf"


def test_la_etiqueta_de_contexto_llega_al_registro_y_se_restaura(cliente, monkeypatch):
    _postear(monkeypatch, _ok(), _ok())

    with contexto_llamada(cliente, co="CO0100002908", tipo="acta_texto", acta="VIPE"):
        cliente.enviar(BODY_TEXTO)
    cliente.enviar(BODY_TEXTO)

    primero, segundo = cliente.registros
    assert (primero["co"], primero["tipo"], primero["acta"]) == ("CO0100002908", "acta_texto", "VIPE")
    assert segundo["co"] is None and segundo["tipo"] == "texto"  # la etiqueta no se filtra a la llamada siguiente


def test_el_origen_lote_se_conserva_dentro_de_otra_etiqueta(cliente, monkeypatch):
    _postear(monkeypatch, _ok())
    cliente.contexto = {"origen": "lote"}

    with contexto_llamada(cliente, co="CO1", tipo="acta_texto"):
        cliente.enviar(BODY_TEXTO)

    assert cliente.registros[0]["origen"] == "lote" and cliente.registros[0]["co"] == "CO1"


def test_cuenta_los_intentos_fallidos_antes_del_exito(cliente, monkeypatch):
    _postear(monkeypatch, requests.Timeout("lento"), Resp(503, text="x"), _ok())

    cliente.enviar(BODY_TEXTO)

    (r,) = cliente.registros
    assert r["intentos"] == 3 and r["fallidos"] == 2 and r["resultado"] == "ok"


def test_registra_el_error_cuando_se_agotan_los_reintentos(cliente, monkeypatch):
    _postear(monkeypatch, Resp(503, text="a"), Resp(503, text="b"), Resp(503, text="c"))

    with pytest.raises(AnthropicRateLimitError):
        cliente.enviar(BODY_TEXTO)

    (r,) = cliente.registros
    assert r["resultado"] == "error" and r["fallidos"] == 3 and r["error"] == "AnthropicRateLimitError"


def test_registra_el_error_del_limite_de_gasto(cliente, monkeypatch):
    msg = '{"error":{"message":"You have reached your specified API usage limits."}}'
    _postear(monkeypatch, Resp(400, text=msg))

    with pytest.raises(RuntimeError, match="usage limits"):
        cliente.enviar(BODY_TEXTO)

    (r,) = cliente.registros
    assert r["resultado"] == "error" and r["error"] == "HTTP 400" and r["intentos"] == 1


def test_un_registrador_que_falla_no_rompe_la_extraccion(cliente, monkeypatch):
    def roto(registro):
        raise RuntimeError("Sheets caído")

    cliente.registrador = roto
    _postear(monkeypatch, _ok())

    assert cliente.enviar(BODY_TEXTO) == "{}"  # sigue devolviendo la respuesta


def test_sin_registrador_funciona_igual(monkeypatch):
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    c = AnthropicClient(AnthropicConfig(api_key="fake"))
    _postear(monkeypatch, _ok())

    assert c.enviar(BODY_TEXTO) == "{}"


def test_contexto_llamada_ignora_objetos_sin_contexto():
    class Otro:
        pass

    with contexto_llamada(Otro(), co="CO1"):  # no debe lanzar
        pass
