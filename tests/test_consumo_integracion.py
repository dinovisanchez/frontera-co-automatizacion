"""De punta a punta: una extracción de acta con Claude simulado deja una fila etiquetada en la hoja
de consumo, y el endpoint /api/consumo_resumen la resume. Sin llamar a Anthropic ni a Sheets."""

import json

import pytest

from config.settings import AnthropicConfig
from core.data_sources import llm_client
from core.data_sources.llm_client import AnthropicClient
from core.services import or_extractor
from core.services.acta_analyzer import MetadatosActa, analizar_acta_desde_pdf, analizar_acta_desde_texto
from core.services.consumo import COLUMNAS, ConsumoStore
from tests.test_consumo import HojaFalsa, SheetsFalso
from tests.test_llm_client_consumo import Resp

_RESPUESTA = '```json\n{"tipo_medida_actual": "semidirecta", "capacidad_instalada_kva": 75}\n```'


def _llm_con_registro(monkeypatch, sheets):
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    llm = AnthropicClient(AnthropicConfig(api_key="fake"))
    llm.registrador = ConsumoStore(sheets).registrar
    uso = {"input_tokens": 300, "cache_read_input_tokens": 2500, "output_tokens": 900}
    monkeypatch.setattr(
        llm_client.requests, "post",
        lambda *a, **k: Resp(200, {"content": [{"type": "text", "text": _RESPUESTA}], "stop_reason": "end_turn", "usage": uso}),
    )
    return llm


def _filas(sheets):
    return [dict(zip(COLUMNAS, f)) for f in sheets.hoja.filas]


def test_extraccion_de_acta_en_texto_queda_etiquetada(monkeypatch):
    sheets = SheetsFalso(HojaFalsa())
    llm = _llm_con_registro(monkeypatch, sheets)
    meta = MetadatosActa(co="CO0100002908", tipo_acta="VIPE", fecha_visita="2026-01-01")

    resultado = analizar_acta_desde_texto(meta, "texto ocr", llm)

    assert resultado.spec["tipo_medida_actual"] == "semidirecta"  # la extracción sigue funcionando igual
    (fila,) = _filas(sheets)
    assert (fila["co"], fila["tipo"], fila["acta"], fila["origen"]) == ("CO0100002908", "acta_texto", "VIPE", "individual")
    # La lectura por TEXTO va con Sonnet 5.5 (config.settings.model_acta_texto): sus precios, no los de Opus 5.
    assert (fila["modelo"], fila["esfuerzo"], fila["resultado"]) == ("claude-sonnet-5-5", "medium", "ok")
    assert fila["costo_usd"] == pytest.approx((300 * 2 + 2500 * 0.2 + 900 * 10) / 1e6)


def test_extraccion_con_pdf_se_distingue_de_la_de_texto(monkeypatch):
    sheets = SheetsFalso(HojaFalsa())
    llm = _llm_con_registro(monkeypatch, sheets)
    meta = MetadatosActa(co="CO0100002908", tipo_acta="INST", fecha_visita="2026-01-01")

    analizar_acta_desde_pdf(meta, b"%PDF-fake", llm)

    assert _filas(sheets)[0]["tipo"] == "acta_pdf"


def test_pregunta_del_operador_lleva_su_co(monkeypatch):
    sheets = SheetsFalso(HojaFalsa())
    llm = _llm_con_registro(monkeypatch, sheets)
    monkeypatch.setattr(
        llm_client.requests, "post",
        lambda *a, **k: Resp(200, {"content": [{"type": "text", "text": '{"or": "AFINIA"}'}], "usage": {"input_tokens": 10, "output_tokens": 5}}),
    )

    assert or_extractor.extraer_or_desde_pdf(b"%PDF-fake", llm, co="CO0100002908") == "AFINIA"

    fila = _filas(sheets)[0]
    assert (fila["co"], fila["tipo"], fila["esfuerzo"]) == ("CO0100002908", "operador", "low")


def test_el_endpoint_resume_lo_registrado(monkeypatch):
    from api import consumo_resumen
    from api.index import app

    sheets = SheetsFalso(HojaFalsa())
    llm = _llm_con_registro(monkeypatch, sheets)
    meta = MetadatosActa(co="CO0100002908", tipo_acta="VIPE", fecha_visita="2026-01-01")
    analizar_acta_desde_texto(meta, "t1", llm)
    analizar_acta_desde_texto(meta, "t2", llm)

    class Deps:
        pass

    deps = Deps()
    deps.sheets = sheets
    monkeypatch.setattr(consumo_resumen, "construir_dependencias", lambda requiere_metabase=False: deps)

    resp = app.test_client().get("/api/consumo_resumen")

    assert resp.status_code == 200
    cuerpo = json.loads(resp.data)
    assert cuerpo["llamadas"] == 2 and cuerpo["cos_distintos"] == 1 and cuerpo["llamadas_medias_por_co"] == 2
    assert cuerpo["por_tipo"]["acta_texto"]["llamadas"] == 2


def test_el_endpoint_rechaza_una_fecha_mal_escrita():
    from api.index import app

    resp = app.test_client().get("/api/consumo_resumen?desde=ayer")

    assert resp.status_code == 400
