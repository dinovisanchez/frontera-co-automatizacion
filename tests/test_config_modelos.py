"""Qué modelo usa cada tipo de llamada a Claude: la lectura de actas por TEXTO va con Sonnet 5.5 (decisión del
2026-10-01, ver config.settings); todo lo demás (acta por PDF, operador de red, certificados) sigue con Opus 5."""

import pytest

from config.settings import AnthropicConfig, PRECIOS_USD_POR_MTOK, cargar_anthropic_config
from core.data_sources.llm_client import AnthropicClient

SISTEMA = "prompt"
MENSAJE = [{"type": "text", "text": "hola"}]


def test_defaults_de_produccion():
    cfg = AnthropicConfig(api_key="x")

    assert (cfg.model_acta_texto, cfg.effort_acta_texto) == ("claude-sonnet-5-5", "medium")
    assert (cfg.model, cfg.effort, cfg.max_tokens) == ("claude-opus-5", "medium", 2000)  # lo demás NO cambió
    assert cfg.model_acta_texto in PRECIOS_USD_POR_MTOK  # si no, el costo saldría en blanco en "Consumo"


def test_solo_la_lectura_por_texto_usa_sonnet():
    llm = AnthropicClient(AnthropicConfig(api_key="x"))

    texto = llm.cuerpo_extraccion_acta_texto(SISTEMA, MENSAJE)
    pdf = llm.cuerpo_extraccion_acta(SISTEMA, MENSAJE)
    puntual = llm.cuerpo_extraccion_puntual(SISTEMA, MENSAJE, max_tokens=300, effort="low")

    assert (texto["model"], texto["output_config"]) == ("claude-sonnet-5-5", {"effort": "medium"})
    assert (pdf["model"], pdf["output_config"]) == ("claude-opus-5", {"effort": "medium"})
    assert (puntual["model"], puntual["output_config"]) == ("claude-opus-5", {"effort": "low"})
    # el resto del body es el de siempre (mismos max_tokens, prompt cacheado y mensajes)
    assert texto["max_tokens"] == pdf["max_tokens"] == 2000
    assert texto["system"] == pdf["system"] and texto["messages"] == pdf["messages"]
    assert texto["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_sin_variables_opcionales_rige_el_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("ACTA_TEXTO_MODELO", raising=False)
    monkeypatch.delenv("ACTA_TEXTO_ESFUERZO", raising=False)

    cfg = cargar_anthropic_config()

    assert (cfg.model_acta_texto, cfg.effort_acta_texto) == ("claude-sonnet-5-5", "medium")


def test_se_puede_volver_a_opus_con_variables_de_entorno_sin_tocar_codigo(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("ACTA_TEXTO_MODELO", " claude-opus-5 ")
    monkeypatch.setenv("ACTA_TEXTO_ESFUERZO", "low")

    cfg = cargar_anthropic_config()
    cuerpo = AnthropicClient(cfg).cuerpo_extraccion_acta_texto(SISTEMA, MENSAJE)

    assert (cfg.model_acta_texto, cfg.effort_acta_texto) == ("claude-opus-5", "low")
    assert (cuerpo["model"], cuerpo["output_config"]) == ("claude-opus-5", {"effort": "low"})
    assert cfg.model == "claude-opus-5"  # las otras llamadas no se afectan


def test_el_api_key_sigue_siendo_obligatorio(monkeypatch):
    from config.settings import ConfigError

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        cargar_anthropic_config()
