"""consumo.py — costo estimado, fila de la hoja, almacenamiento mejor-esfuerzo y resumen."""

import pytest

from core.services import consumo
from core.services.consumo import COLUMNAS, ConsumoStore, costo_usd, fila_desde_registro, resumir


def test_costo_de_una_llamada_con_los_precios_oficiales_de_opus_5():
    # 300 entrada nueva + 2.500 leídos de caché + 1.500 de salida:
    # 300*5 + 2500*0.50 + 1500*25 = 1.500 + 1.250 + 37.500 = 40.250 -> $0.04025
    assert costo_usd("claude-opus-5", 300, 0, 2500, 1500) == pytest.approx(0.04025)


def test_escritura_de_cache_se_cobra_a_1_25x_la_entrada():
    assert costo_usd("claude-opus-5", 0, 2000, 0, 0) == pytest.approx(2000 * 6.25 / 1e6)


def test_opus_5_5_es_un_20_por_ciento_mas_barato_que_opus_5_en_entrada_y_salida():
    assert costo_usd("claude-opus-5-5", 1_000_000, 0, 0, 0) == pytest.approx(4.0)
    assert costo_usd("claude-opus-5-5", 0, 0, 0, 1_000_000) == pytest.approx(20.0)


def test_modelo_desconocido_no_inventa_un_costo():
    assert costo_usd("modelo-que-no-existe", 1, 1, 1, 1) is None


def test_fila_respeta_el_orden_de_columnas_y_calcula_el_costo():
    reg = {"fecha_utc": "2026-10-01T12:00:00Z", "co": "CO1", "tipo": "acta_texto", "modelo": "claude-opus-5",
           "entrada": 300, "lectura_cache": 2500, "salida": 1500, "resultado": "ok", "intentos": 1}

    fila = fila_desde_registro(reg)

    assert len(fila) == len(COLUMNAS)
    por_nombre = dict(zip(COLUMNAS, fila))
    assert por_nombre["co"] == "CO1" and por_nombre["costo_usd"] == pytest.approx(0.04025)
    assert por_nombre["razonamiento"] == "" and por_nombre["error"] == ""  # lo que no hay queda en blanco


class HojaFalsa:
    def __init__(self, filas=None, falla=False):
        self.filas, self.falla = filas if filas is not None else [], falla

    def append_row(self, fila, value_input_option=None, table_range=None):
        if self.falla:
            raise RuntimeError("429")
        assert table_range == "A1" and value_input_option == "RAW"
        self.filas.append(fila)

    def get_all_values(self):
        return [COLUMNAS] + self.filas

    def update(self, valores, range_name=None):
        self.encabezado = valores


class SheetsFalso:
    def __init__(self, hoja=None):
        self.hoja, self.creada = hoja, False

    def hoja_por_nombre(self, nombre):
        assert nombre == "PyConsumo"
        if self.hoja is None:
            raise RuntimeError("no existe")
        return self.hoja

    def crear_hoja(self, nombre, filas, columnas):
        self.creada, self.hoja = True, HojaFalsa()
        return self.hoja


def test_registrar_crea_la_pestana_con_encabezado_si_no_existe():
    sheets = SheetsFalso()
    ConsumoStore(sheets).registrar({"fecha_utc": "2026-10-01T12:00:00Z", "modelo": "claude-opus-5", "resultado": "ok"})

    assert sheets.creada and sheets.hoja.encabezado == [COLUMNAS] and len(sheets.hoja.filas) == 1


def test_registrar_nunca_lanza_aunque_sheets_falle(capsys):
    ConsumoStore(SheetsFalso(HojaFalsa(falla=True))).registrar({"resultado": "ok"})  # no debe lanzar

    assert "no se pudo registrar" in capsys.readouterr().err


def test_leer_convierte_numeros_y_filtra_por_fecha():
    hoja = HojaFalsa([
        fila_desde_registro({"fecha_utc": "2026-09-30T10:00:00Z", "co": "A", "modelo": "claude-opus-5", "entrada": 100, "salida": 10, "resultado": "ok"}),
        fila_desde_registro({"fecha_utc": "2026-10-01T10:00:00Z", "co": "B", "modelo": "claude-opus-5", "entrada": 200, "salida": 20, "resultado": "ok"}),
    ])
    store = ConsumoStore(SheetsFalso(hoja))

    todos = store.leer()
    desde = store.leer(desde="2026-10-01")

    assert [r["co"] for r in todos] == ["A", "B"] and todos[0]["entrada"] == 100.0
    assert [r["co"] for r in desde] == ["B"]


def _reg(co, tipo="acta_texto", modelo="claude-opus-5", entrada=300, lectura=2500, salida=1000, razon=600, stop="end_turn", intentos=1, fallidos=0, seg=4.0, origen="individual", esfuerzo="medium"):
    return {"fecha_utc": "2026-10-01T10:00:00Z", "co": co, "tipo": tipo, "origen": origen, "modelo": modelo, "esfuerzo": esfuerzo,
            "entrada": entrada, "escritura_cache": 0, "lectura_cache": lectura, "salida": salida, "razonamiento": razon,
            "stop_reason": stop, "intentos": intentos, "fallidos": fallidos, "segundos": seg, "resultado": "ok", "error": None,
            "costo_usd": costo_usd(modelo, entrada, 0, lectura, salida)}


def test_resumen_por_co_y_proyeccion():
    # CO1: 2 llamadas; CO2: 1 llamada.
    r = resumir([_reg("CO1"), _reg("CO1"), _reg("CO2")])

    un_call = costo_usd("claude-opus-5", 300, 0, 2500, 1000)
    assert r["llamadas"] == 3 and r["cos_distintos"] == 2
    assert r["costo_total_usd"] == pytest.approx(3 * un_call, abs=1e-4)
    assert r["costo_medio_por_co_usd"] == pytest.approx(1.5 * un_call, abs=1e-4)  # (2 + 1) / 2 COs
    assert r["llamadas_medias_por_co"] == 1.5
    assert r["proyeccion_usd"]["400_cos"] == pytest.approx(round(1.5 * un_call * 400, 2), abs=0.01)


def test_resumen_detecta_las_fugas_que_sospechamos():
    r = resumir([
        _reg("CO1", stop="max_tokens"), _reg("CO2"),
        _reg("CO3", intentos=3, fallidos=2),
        {"fecha_utc": "2026-10-01T10:00:00Z", "co": "CO4", "tipo": "acta_texto", "modelo": "claude-opus-5", "intentos": 3, "fallidos": 3,
         "resultado": "error", "error": "AnthropicRateLimitError"},
    ])

    assert r["respuestas_cortadas"] == {"cantidad": 1, "pct": pytest.approx(1 / 3, abs=1e-4)}
    assert r["reintentos"]["llamadas_con_reintentos"] == 2 and r["reintentos"]["intentos_fallidos_totales"] == 5
    assert r["llamadas_con_error"] == 1 and r["errores_por_tipo"] == {"AnthropicRateLimitError": 1}
    assert r["razonamiento_pct_de_salida"] == pytest.approx(0.6)  # 600 de 1.000 tokens de salida


def test_resumen_tasa_de_cache_y_agrupaciones():
    r = resumir([
        _reg("CO1", entrada=500, lectura=2500, origen="lote"),
        _reg("CO2", tipo="acta_pdf", modelo="claude-opus-5-5", esfuerzo="low", entrada=5000, lectura=0, origen="individual"),
    ])

    assert r["cache_tasa_aciertos"] == pytest.approx(2500 / (500 + 2500 + 5000), abs=1e-4)
    assert set(r["por_tipo"]) == {"acta_texto", "acta_pdf"}
    assert set(r["por_configuracion"]) == {"claude-opus-5 · esfuerzo medium", "claude-opus-5-5 · esfuerzo low"}
    assert set(r["por_origen"]) == {"lote", "individual"}


def test_resumen_sin_datos_no_revienta():
    r = resumir([])

    assert r["llamadas"] == 0 and r["costo_total_usd"] == 0 and r["costo_medio_por_co_usd"] is None and r["proyeccion_usd"] is None
    assert r["cache_tasa_aciertos"] is None and r["desde"] is None
