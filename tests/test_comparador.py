"""comparador.py + /api/comparar_config con Claude, Metabase, Drive y Sheets simulados — no gasta nada."""

import json

import pytest

from config.settings import AnthropicConfig
from core.data_sources import llm_client
from core.services import comparador
from core.services.acta_analyzer import MetadatosActa
from core.services.comparador import ID_ACTUAL, comparar_acta_texto, comparar_specs, normalizar_valor
from tests.test_llm_client_consumo import Resp

META = MetadatosActa(co="CO0100002908", tipo_acta="VIPE", fecha_visita="2026-01-01")
CFG = AnthropicConfig(api_key="fake")  # modelo claude-opus-5, esfuerzo medium


def test_normalizar_valor_ignora_formato_pero_no_significado():
    assert normalizar_valor(75) == normalizar_valor("75.0") == normalizar_valor("75,0") == "75"
    assert normalizar_valor(" Semidirecta ") == normalizar_valor("semidirecta")
    assert normalizar_valor(["B", "a"]) == normalizar_valor(["a", "b"])
    assert normalizar_valor(None) is normalizar_valor("") is normalizar_valor([]) is None
    assert normalizar_valor("200/5") != normalizar_valor("300/5")
    assert normalizar_valor(True) != normalizar_valor(False)


def test_comparar_specs_clasifica_cada_campo():
    actual = {"tipo_medida_actual": "directa", "nivel_tension": 1, "capacidad_instalada_kva": 75, "relacion_tc": "200/5", "trafo_uso": None}
    candidata = {"tipo_medida_actual": "Directa", "nivel_tension": 2, "capacidad_instalada_kva": None, "relacion_tc": "200/5", "trafo_uso": "exclusivo"}

    r = comparar_specs(actual, candidata)

    assert r["diferencias"]["nivel_tension"]["estado"] == "diferente"
    assert r["diferencias"]["capacidad_instalada_kva"]["estado"] == "solo_actual"  # la candidata lo dejó vacío
    assert r["diferencias"]["trafo_uso"]["estado"] == "solo_candidata"             # la actual lo dejó vacío
    assert "tipo_medida_actual" not in r["diferencias"] and "relacion_tc" not in r["diferencias"]  # coinciden
    assert r["conteo"]["diferente"] == 1 and r["total"] == 12
    assert r["coinciden"] == 12 - 3  # los 3 distintos; el resto (vacío == vacío) coincide


def test_observaciones_y_supuestos_no_cuentan_como_desacuerdo():
    r = comparar_specs({"observaciones": "uno", "supuestos": ["a"]}, {"observaciones": "otro texto", "supuestos": []})

    assert r["coinciden"] == r["total"] and r["diferencias"] == {}


def test_candidata_sin_resultado():
    r = comparar_specs({"tipo_medida_actual": "directa"}, None)

    assert r["coinciden"] == 0 and r["conteo"]["sin_resultado"] == 12


def _json(**campos):
    return "```json\n" + json.dumps(campos) + "\n```"


def _claude_simulado(monkeypatch, por_modelo):
    """`por_modelo`: modelo -> (texto de respuesta | Exception, tokens de salida)."""
    def post(url, headers=None, json=None, timeout=None):
        respuesta, salida = por_modelo[json["model"]]
        if isinstance(respuesta, Exception):
            return Resp(400, text=str(respuesta))
        return Resp(200, {"content": [{"type": "text", "text": respuesta}], "stop_reason": "end_turn",
                          "usage": {"input_tokens": 4000, "cache_read_input_tokens": 2500, "output_tokens": salida}})

    monkeypatch.setattr(llm_client.requests, "post", post)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)


def test_compara_la_misma_acta_con_la_actual_y_las_candidatas(monkeypatch):
    base = {"tipo_medida_actual": "semidirecta", "nivel_tension": 1, "capacidad_instalada_kva": 75}
    _claude_simulado(monkeypatch, {
        "claude-opus-5": (_json(**base), 1200),
        "claude-opus-5-5": (_json(**base), 1000),
        "claude-sonnet-5-5": (_json(**{**base, "capacidad_instalada_kva": 150}), 600),
    })

    r = comparar_acta_texto(META, "texto ocr", CFG, ["opus-5-5-medio", "sonnet-5-5-medio"])

    por_id = {c["id"]: c for c in r["configuraciones"]}
    assert list(por_id) == [ID_ACTUAL, "opus-5-5-medio", "sonnet-5-5-medio"]
    assert por_id[ID_ACTUAL]["modelo"] == "claude-opus-5" and por_id["sonnet-5-5-medio"]["esfuerzo"] == "medium"
    assert r["comparaciones"]["opus-5-5-medio"]["coinciden"] == 12                      # idéntica a la actual
    assert r["comparaciones"]["sonnet-5-5-medio"]["diferencias"]["capacidad_instalada_kva"]["estado"] == "diferente"
    # costo = (4000 entrada*5 + 2500 caché*0.5 + salida*25)/1e6 con los precios de cada modelo
    assert por_id[ID_ACTUAL]["costo_usd"] == pytest.approx((4000 * 5 + 2500 * 0.5 + 1200 * 25) / 1e6)
    assert por_id["sonnet-5-5-medio"]["costo_usd"] == pytest.approx((4000 * 2 + 2500 * 0.2 + 600 * 10) / 1e6)
    assert por_id["sonnet-5-5-medio"]["costo_usd"] < por_id["opus-5-5-medio"]["costo_usd"] < por_id[ID_ACTUAL]["costo_usd"]
    assert len(por_id[ID_ACTUAL]["registros"]) == 1 and por_id[ID_ACTUAL]["registros"][0]["origen"] == "comparacion"


def test_una_candidata_que_falla_es_un_resultado_no_un_error(monkeypatch):
    base = {"tipo_medida_actual": "directa"}
    _claude_simulado(monkeypatch, {
        "claude-opus-5": (_json(**base), 800),
        "claude-sonnet-5-5": (RuntimeError("HTTP 400 raro"), 0),
        "claude-opus-5-5": ("no hay json acá", 100),
    })

    r = comparar_acta_texto(META, "texto", CFG, ["sonnet-5-5-medio", "opus-5-5-medio"])

    por_id = {c["id"]: c for c in r["configuraciones"]}
    assert por_id["sonnet-5-5-medio"]["ok"] is False and "400" in por_id["sonnet-5-5-medio"]["error"]
    assert por_id["opus-5-5-medio"]["ok"] is False and "JSON" in por_id["opus-5-5-medio"]["error"]
    assert r["comparaciones"]["sonnet-5-5-medio"]["conteo"]["sin_resultado"] == 12
    assert por_id[ID_ACTUAL]["ok"] is True


# ---------------------------------------------------------------- endpoint

class MetabaseFalso:
    def __init__(self, filas):
        self.filas = filas

    def filas_por_co(self, co):
        return [f for f in self.filas if f["bia_code"] == co]


class Deps:
    drive_cfg = object()

    def __init__(self, filas):
        self.metabase = MetabaseFalso(filas)
        self.sheets = object()


@pytest.fixture
def api(monkeypatch):
    from api import comparar_config
    from api.index import app
    from core.services.acta_downloader import ResultadoDescarga
    from core.services.acta_ocr import OcrResultado

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    filas = [
        {"bia_code": "CO0100002908", "service_type_id": "VIPE", "fecha_visita": "2026-02-01", "act_pdf_url": "https://x/reciente.pdf"},
        {"bia_code": "CO0100002908", "service_type_id": "INST", "fecha_visita": "2025-01-01", "act_pdf_url": "https://x/vieja.pdf"},
    ]
    monkeypatch.setattr(comparar_config, "construir_dependencias", lambda: Deps(filas))
    monkeypatch.setattr(comparar_config.acta_downloader, "descargar_pdf_acta", lambda url: ResultadoDescarga(ok=True, bytes_pdf=b"%PDF"))
    monkeypatch.setattr(comparar_config.acta_ocr, "ocr_texto_desde_bytes", lambda b, cfg: OcrResultado(ok=True, texto="texto del acta"))
    guardados = []
    monkeypatch.setattr(comparar_config, "get_consumo_store", lambda sheets: type("S", (), {"registrar": lambda self, r: guardados.append(r)})())
    return app.test_client(), guardados


def test_endpoint_compara_el_acta_mas_reciente_y_guarda_el_consumo(api, monkeypatch):
    cliente, guardados = api
    _claude_simulado(monkeypatch, {"claude-opus-5": (_json(tipo_medida_actual="directa"), 900), "claude-opus-5-5": (_json(tipo_medida_actual="directa"), 700)})

    resp = cliente.post("/api/comparar_config", json={"co": "co0100002908", "indice": 0, "candidatas": ["opus-5-5-medio"]})

    cuerpo = resp.get_json()
    assert resp.status_code == 200 and cuerpo["total_actas"] == 2
    assert cuerpo["acta"] == {"indice": 0, "tipo": "VIPE", "fecha": "2026-02-01", "url": "https://x/reciente.pdf"}
    assert cuerpo["comparaciones"]["opus-5-5-medio"]["coinciden"] == 12 and cuerpo["ocr_caracteres"] == len("texto del acta")
    assert all("registros" not in c for c in cuerpo["configuraciones"])
    assert {r["modelo"] for r in guardados} == {"claude-opus-5", "claude-opus-5-5"}
    assert all(r["co"] == "CO0100002908" and r["origen"] == "comparacion" for r in guardados)


def test_endpoint_indice_mayor_al_de_actas_disponibles(api):
    cliente, _ = api

    cuerpo = cliente.post("/api/comparar_config", json={"co": "CO0100002908", "indice": 3, "candidatas": ["opus-5-5-medio"]}).get_json()

    assert cuerpo == {"co": "CO0100002908", "total_actas": 2, "sin_acta": True}


@pytest.mark.parametrize("body", [
    {"indice": 0, "candidatas": ["opus-5-5-medio"]},                                   # sin CO
    {"co": "CO1", "candidatas": []},                                                   # sin candidatas
    {"co": "CO1", "candidatas": ["modelo-inventado"]},                                 # candidata fuera de la lista
    {"co": "CO1", "candidatas": ["opus-5-5-medio", "opus-5-5-bajo", "sonnet-5-5-medio", "sonnet-5-5-bajo"]},  # demasiadas
    {"co": "CO1", "indice": 9, "candidatas": ["opus-5-5-medio"]},                      # índice fuera de rango
    {"co": "CO1", "indice": "0", "candidatas": ["opus-5-5-medio"]},                    # índice no entero
])
def test_endpoint_valida_la_entrada_antes_de_gastar(api, body):
    cliente, _ = api

    assert cliente.post("/api/comparar_config", json=body).status_code == 400


def test_endpoint_co_sin_actas(api):
    cliente, _ = api

    resp = cliente.post("/api/comparar_config", json={"co": "CO9999999999", "candidatas": ["opus-5-5-medio"]})

    assert resp.status_code == 404
