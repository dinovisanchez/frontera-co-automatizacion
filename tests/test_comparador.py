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
        {"bia_code": "CO0100002908", "service_type_id": "VIPE", "fecha_visita": "2026-02-01", "act_pdf_url": "https://x/reciente.pdf", "estado_visita": "Cierre Exitoso"},
        {"bia_code": "CO0100002908", "service_type_id": "INST", "fecha_visita": "2025-01-01", "act_pdf_url": "https://x/vieja.pdf", "estado_visita": "Cierre Exitoso"},
        {"bia_code": "CO0500000005", "service_type_id": "INFR", "fecha_visita": "2026-03-01", "act_pdf_url": "https://x/fallida.pdf", "estado_visita": "Cierre Fallido"},
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
    assert resp.status_code == 200 and cuerpo["total_actas"] == 2 and cuerpo["omitidas"] == []  # 2 candidatas; se usa la primera
    assert cuerpo["acta"] == {"indice": 0, "tipo": "VIPE", "fecha": "2026-02-01", "url": "https://x/reciente.pdf"}
    assert cuerpo["comparaciones"]["opus-5-5-medio"]["coinciden"] == 12 and cuerpo["ocr_caracteres"] == len("texto del acta")
    assert all("registros" not in c for c in cuerpo["configuraciones"])
    assert {r["modelo"] for r in guardados} == {"claude-opus-5", "claude-opus-5-5"}
    assert all(r["co"] == "CO0100002908" and r["origen"] == "comparacion" for r in guardados)


def test_endpoint_rechaza_un_indice_fuera_del_tope_de_candidatas(api):
    cliente, _ = api

    assert cliente.post("/api/comparar_config", json={"co": "CO0100002908", "indice": 3, "candidatas": ["opus-5-5-medio"]}).status_code == 400


def test_endpoint_indice_mayor_al_de_candidatas_disponibles(api):
    cliente, _ = api

    cuerpo = cliente.post("/api/comparar_config", json={"co": "CO0100002908", "indice": 2, "candidatas": ["opus-5-5-medio"]}).get_json()

    assert cuerpo == {"co": "CO0100002908", "total_actas": 2, "sin_acta": True}


def test_si_la_acta_elegida_no_se_puede_leer_se_compara_con_la_siguiente(api, monkeypatch):
    from api import comparar_config
    from core.services.acta_downloader import ResultadoDescarga

    cliente, _ = api
    monkeypatch.setattr(
        comparar_config.acta_downloader, "descargar_pdf_acta",
        lambda url: ResultadoDescarga(ok=False, motivo_fallo="no es un PDF válido") if "reciente" in url else ResultadoDescarga(ok=True, bytes_pdf=b"%PDF"),
    )
    _claude_simulado(monkeypatch, {"claude-opus-5": (_json(tipo_medida_actual="directa"), 900), "claude-opus-5-5": (_json(tipo_medida_actual="directa"), 700)})

    cuerpo = cliente.post("/api/comparar_config", json={"co": "CO0100002908", "candidatas": ["opus-5-5-medio"]}).get_json()

    assert cuerpo["acta"]["tipo"] == "INST" and cuerpo["acta"]["url"] == "https://x/vieja.pdf"  # VIPE falló → la siguiente
    assert [(o["tipo"], o["motivo"]) for o in cuerpo["omitidas"]] == [("VIPE", "No se pudo descargar: no es un PDF válido")]
    assert cuerpo["comparaciones"]["opus-5-5-medio"]["coinciden"] == 12


def test_si_ninguna_candidata_se_puede_leer_no_se_llama_a_claude(api, monkeypatch):
    from api import comparar_config
    from core.services.acta_downloader import ResultadoDescarga
    from core.services.acta_ocr import OcrResultado

    cliente, guardados = api
    monkeypatch.setattr(comparar_config.acta_downloader, "descargar_pdf_acta", lambda url: ResultadoDescarga(ok=True, bytes_pdf=b"%PDF"))
    monkeypatch.setattr(comparar_config.acta_ocr, "ocr_texto_desde_bytes", lambda b, cfg: OcrResultado(ok=False, motivo_fallo="read timed out"))
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: pytest.fail("no debía llamar a Claude"))

    cuerpo = cliente.post("/api/comparar_config", json={"co": "CO0100002908", "candidatas": ["opus-5-5-medio"]}).get_json()

    assert "No se pudo leer ninguna acta candidata" in cuerpo["error"] and len(cuerpo["omitidas"]) == 2 and "read timed out" in cuerpo["error"]
    assert guardados == []


def test_no_se_prueba_otra_candidata_si_ya_no_queda_tiempo(api, monkeypatch):
    from api import comparar_config
    from core.services.acta_ocr import OcrResultado

    cliente, _ = api
    llamadas = []
    monkeypatch.setattr(comparar_config.acta_ocr, "ocr_texto_desde_bytes", lambda b, cfg: (llamadas.append(1), OcrResultado(ok=False, motivo_fallo="timeout"))[1])
    monkeypatch.setattr(comparar_config.time, "monotonic", _reloj(0.0, 40.0))  # el primer OCR se comió 40 s

    cuerpo = cliente.post("/api/comparar_config", json={"co": "CO0100002908", "candidatas": ["opus-5-5-medio"]}).get_json()

    assert len(llamadas) == 1 and len(cuerpo["omitidas"]) == 1 and "reintenta este CO" in cuerpo["error"]


def test_endpoint_co_sin_visita_exitosa_explica_el_motivo(api):
    cliente, _ = api

    resp = cliente.post("/api/comparar_config", json={"co": "CO0500000005", "candidatas": ["opus-5-5-medio"]})

    assert resp.status_code == 404
    error = resp.get_json()["error"]
    assert error.startswith('"CO0500000005" no tiene ninguna acta') and "Cierre Fallido" in error  # el frontend reconoce el prefijo


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


# ---------------------------------------------------------------- límite de tiempo (504)

def _reloj(*valores):
    """time.monotonic simulado: devuelve los valores en orden y después repite el último."""
    it, ultimo = iter(valores), [valores[-1]]

    def reloj():
        ultimo[0] = next(it, ultimo[0])
        return ultimo[0]

    return reloj


def test_la_comparacion_hace_un_solo_intento_con_el_tiempo_que_le_dan(monkeypatch):
    import requests as _requests

    llamadas = []

    def post(url, headers=None, json=None, timeout=None):
        llamadas.append((json["model"], timeout))
        raise _requests.Timeout("lento")

    monkeypatch.setattr(llm_client.requests, "post", post)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

    r = comparar_acta_texto(META, "texto", CFG, ["sonnet-5-5-medio"], timeout_seg=30)

    assert sorted(llamadas) == [("claude-opus-5", 30), ("claude-sonnet-5-5", 30)]  # 1 intento por configuración, no 3
    assert all(c["ok"] is False and "No respondió en 30 s" in c["error"] for c in r["configuraciones"])


def test_sin_timeout_se_conservan_los_intentos_de_produccion(monkeypatch):
    import requests as _requests

    intentos = []
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: (intentos.append(k["timeout"]), (_ for _ in ()).throw(_requests.Timeout("x")))[1])
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

    comparar_acta_texto(META, "texto", CFG, ["opus-5-5-medio"])

    assert intentos.count(15) == 6  # 2 configuraciones x 3 intentos de 15 s, como en producción


def test_endpoint_no_llama_a_claude_si_el_ocr_se_comio_el_tiempo(api, monkeypatch):
    from api import comparar_config

    cliente, guardados = api
    monkeypatch.setattr(comparar_config.time, "monotonic", _reloj(0.0, 50.0))  # inicio; tras descargar+OCR: 50 s gastados de 55
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: pytest.fail("no debía llamar a Claude"))

    cuerpo = cliente.post("/api/comparar_config", json={"co": "CO0100002908", "candidatas": ["opus-5-5-medio"]}).get_json()

    assert "ya no quedaba tiempo" in cuerpo["error"] and "No se gastó nada" in cuerpo["error"]
    assert guardados == []


def test_endpoint_pasa_a_claude_el_tiempo_que_queda(api, monkeypatch):
    from api import comparar_config

    cliente, _ = api
    monkeypatch.setattr(comparar_config.time, "monotonic", _reloj(0.0, 20.0))  # 20 s gastados: quedan 35, menos 5 de margen = 30 s por llamada
    timeouts = []

    def post(url, headers=None, json=None, timeout=None):
        timeouts.append(timeout)
        return Resp(200, {"content": [{"type": "text", "text": _json(tipo_medida_actual="directa")}], "usage": {"input_tokens": 10, "output_tokens": 5}})

    monkeypatch.setattr(llm_client.requests, "post", post)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

    cliente.post("/api/comparar_config", json={"co": "CO0100002908", "candidatas": ["opus-5-5-medio"]})

    assert timeouts and set(timeouts) == {30.0}
