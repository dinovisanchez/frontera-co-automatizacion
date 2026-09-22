"""or_extractor.py con un AnthropicClient falso — nunca llama a la API real de Anthropic."""

from config.settings import AnthropicConfig
from core.data_sources.llm_client import AnthropicClient
from core.services.or_extractor import extraer_or_desde_pdf


class AnthropicClientFalso(AnthropicClient):
    def __init__(self, texto_respuesta: str):
        super().__init__(AnthropicConfig(api_key="fake-no-se-usa"))
        self._texto_respuesta = texto_respuesta

    def enviar(self, body: dict) -> str:
        return self._texto_respuesta


def test_extrae_el_or_cuando_el_llm_lo_encuentra():
    llm = AnthropicClientFalso('{"or": "AFINIA"}')

    assert extraer_or_desde_pdf(b"%PDF-fake", llm) == "AFINIA"


def test_devuelve_none_si_el_llm_no_lo_encuentra():
    llm = AnthropicClientFalso('{"or": null}')

    assert extraer_or_desde_pdf(b"%PDF-fake", llm) is None


def test_devuelve_none_si_la_respuesta_no_trae_json():
    llm = AnthropicClientFalso("no hay nada útil acá")

    assert extraer_or_desde_pdf(b"%PDF-fake", llm) is None
