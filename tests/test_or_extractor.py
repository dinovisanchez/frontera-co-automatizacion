"""or_extractor.py con un AnthropicClient falso — nunca llama a la API real de Anthropic."""

from config.settings import AnthropicConfig
from core.data_sources.llm_client import AnthropicClient
from core.services.or_extractor import extraer_or_desde_pdf, extraer_or_desde_texto


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


# ---------------------------------------------------------------- por TEXTO (Sonnet)

def test_extrae_el_or_desde_el_texto_ocr():
    llm = AnthropicClientFalso('{"or": "AFINIA"}')

    assert extraer_or_desde_texto("OR: AFINIA ...", llm, co="CO0100002908") == "AFINIA"


def test_desde_texto_devuelve_none_si_no_lo_encuentra_o_no_hay_json():
    assert extraer_or_desde_texto("texto", AnthropicClientFalso('{"or": null}')) is None
    assert extraer_or_desde_texto("texto", AnthropicClientFalso("nada útil")) is None


def test_desde_texto_nunca_lanza_si_claude_falla():
    class Roto(AnthropicClientFalso):
        def enviar(self, body):
            raise RuntimeError("Claude respondió HTTP 400")

    assert extraer_or_desde_texto("texto", Roto("")) is None


def test_desde_texto_manda_el_texto_con_sonnet_y_no_un_pdf():
    enviados = []

    class Capturador(AnthropicClientFalso):
        def enviar(self, body):
            enviados.append(body)
            return '{"or": "ESSA"}'

    extraer_or_desde_texto("OR: ESSA\nfrontera 123", Capturador(""), co="CO1")

    (body,) = enviados
    assert body["model"] == "claude-sonnet-5-5" and body["output_config"] == {"effort": "medium"}
    (bloque,) = body["messages"][0]["content"]
    assert bloque["type"] == "text" and "OR: ESSA" in bloque["text"]  # texto, no un bloque "document" con el PDF
    assert body["max_tokens"] >= 1000  # holgado: el razonamiento cuenta como salida
