"""acta_analyzer.py con un AnthropicClient falso — nunca llama a la API real de Anthropic."""

from config.settings import AnthropicConfig
from core.data_sources.llm_client import AnthropicClient
from core.services.acta_analyzer import MetadatosActa, analizar_acta_desde_texto

_RESPUESTA_CANNED = """RESUMEN:
tipo_medida_actual: semidirecta
nivel_tension: 120/208
capacidad_instalada_kva: 75
trafo_uso: exclusivo
ubicacion_medida: interior

ANALISIS_LISTO
```json
{
  "tipo_medida_actual": "semidirecta",
  "nivel_tension": "120/208",
  "capacidad_instalada_kva": 75,
  "trafo_uso": "exclusivo",
  "ubicacion_medida": "interior",
  "recuperable_por_cable": true,
  "observaciones": ""
}
```"""


class AnthropicClientFalso(AnthropicClient):
    def __init__(self, texto_respuesta: str):
        super().__init__(AnthropicConfig(api_key="fake-no-se-usa"))
        self._texto_respuesta = texto_respuesta

    def enviar(self, body: dict) -> str:  # nunca hace una petición HTTP real
        return self._texto_respuesta


def test_analizar_acta_desde_texto_parsea_y_normaliza_los_14_campos():
    llm = AnthropicClientFalso(_RESPUESTA_CANNED)
    meta = MetadatosActa(co="CO0100002908", tipo_acta="VIPE", fecha_visita="2026-01-01")

    resultado = analizar_acta_desde_texto(meta, "texto ocr de prueba", llm)

    assert resultado.spec["tipo_medida_actual"] == "semidirecta"
    assert resultado.spec["capacidad_instalada_kva"] == 75
    # Campos que el LLM NO devolvió en este ejemplo deben quedar en None — NUNCA inventados.
    assert resultado.spec["elementos_medida"] is None
    assert resultado.spec["relacion_tc"] is None
    assert resultado.spec["supuestos"] == []
    assert set(resultado.spec.keys()) == {
        "tipo_medida_actual", "nivel_tension", "capacidad_instalada_kva", "trafo_uso",
        "ubicacion_medida", "elementos_medida", "relacion_tc", "relacion_tp", "montaje_tc",
        "totalizador_amperios", "conductor_calibre", "recuperable_por_cable", "observaciones", "supuestos",
    }


def test_spec_none_si_el_llm_no_devuelve_json_valido():
    llm = AnthropicClientFalso("No hay JSON acá, solo texto suelto.")
    meta = MetadatosActa(co="CO0100002908", tipo_acta="VIPE", fecha_visita="2026-01-01")

    resultado = analizar_acta_desde_texto(meta, "texto ocr de prueba", llm)

    assert resultado.spec is None


def test_se_puede_pasar_otro_system_prompt_y_una_respuesta_solo_json_se_parsea():
    from core.prompts.acta_extraction_prompt import ACTA_EXTRACTION_PROMPT_V2, ACTA_EXTRACTION_PROMPT_V2_SOLO_JSON

    enviados = []

    class Capturador(AnthropicClientFalso):
        def enviar(self, body: dict) -> str:
            enviados.append(body["system"][0]["text"])
            return '```json\n{"tipo_medida_actual": "semidirecta", "capacidad_instalada_kva": 75}\n```'  # sin RESUMEN

    meta = MetadatosActa(co="CO0100002908", tipo_acta="VIPE", fecha_visita="2026-01-01")
    llm = Capturador("")

    por_defecto = analizar_acta_desde_texto(meta, "ocr", llm)
    variante = analizar_acta_desde_texto(meta, "ocr", llm, system_prompt=ACTA_EXTRACTION_PROMPT_V2_SOLO_JSON)

    assert enviados == [ACTA_EXTRACTION_PROMPT_V2, ACTA_EXTRACTION_PROMPT_V2_SOLO_JSON]  # producción sigue usando V2
    assert por_defecto.spec["tipo_medida_actual"] == variante.spec["tipo_medida_actual"] == "semidirecta"
    assert variante.resumen == ""  # nadie lo usa; que falte no rompe nada
