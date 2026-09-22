"""analizar_alcance_provisional — orquestador final, con un SheetsClient falso (sin
credenciales reales). Reproduce el caso real CO0200002425 corrido end-to-end.
"""

from core.services.alcance_provisional import analizar_alcance_provisional


class HojaFalsa:
    row_count = 10


class SheetsClientFalso:
    """Ninguna de las 3 hojas externas de ingeniería trae nada para este CO (fallback total a
    lo que ya combinó el job de actas) — ref_capex trae solo el TC real de CO0200002425."""

    def hoja_por_gid(self, gid):
        return HojaFalsa()

    def hoja_por_nombre(self, nombre):
        return HojaFalsa()

    def hoja_externa_por_gid(self, spreadsheet_id, gid):
        return None

    def leer_rango(self, hoja, fila_inicio, col_inicio, num_filas, num_cols, sin_formato=False):
        return [[""] * num_cols for _ in range(num_filas)]

    def leer_todo(self, hoja, sin_formato=False):
        return [
            ["SKU / Item CAPEX", "Categoria", "Costo promedio"],
            ["TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV", "Transformador de corriente", 123000],
        ]


_ACTA_RESULTADO = {
    "spec": {
        "tipo_medida_actual": "semidirecta", "nivel_tension": None, "capacidad_instalada_kva": 300,
        "trafo_uso": "compartido", "ubicacion_medida": "interior", "elementos_medida": 3,
        "relacion_tc": "200/5", "relacion_tp": None, "montaje_tc": "ventana",
        "totalizador_amperios": 200, "conductor_calibre": "1/0", "recuperable_por_cable": None,
        "observaciones": "", "supuestos": [],
    },
    "observaciones": [], "actas": [{"url": "https://x/acta.pdf", "tipo": "INFR", "fecha": "2025-08-01", "aporte": []}],
    "tiene_acta_instalacion": False,
    "capacidades_encontradas": None, "relaciones_tc_encontradas": None, "cortado_por_tiempo": False,
}

_FILAS_METABASE = [
    {"bia_code": "CO0200002425", "service_type_id": "INFR", "fecha_visita": "2025-08-01", "act_pdf_url": "https://x/acta.pdf",
     "tipo_sku": "Transformador de corriente", "sku": "TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV",
     "marca": "ATEL", "serial": "1C68309", "estado_material": "Bueno",
     "certificado_conformidad": "", "vto_conformidad": "", "certificado_calibracion": "", "vto_calibracion": "",
     "visita_id": "v1"},
]


def test_co0200002425_end_to_end_propone_tc_y_avisa_falta_acta_inst():
    dictamen = {"clasificacion": "normalizacion", "seccionesForzadas": {"tc": True, "celda": True}}

    resultado = analizar_alcance_provisional(SheetsClientFalso(), object(), "co0200002425", dictamen, _ACTA_RESULTADO, _FILAS_METABASE)

    assert resultado["co"] == "CO0200002425"
    assert resultado["diagnostico"]["tipo_medida_final"] == "semidirecta"
    assert resultado["diagnostico"]["reclasificado"] is False

    filas_tc = [f for f in resultado["propuesta"] if f["grupo"] == "TC"]
    assert len(filas_tc) == 1
    assert filas_tc[0]["sku"] == "TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV"
    assert filas_tc[0]["costo_estimado"] == 123000.0

    assert any("acta de INSTALACIÓN" in a for a in resultado["alertas"])


def test_sin_actas_arma_solo_con_hoja_maestra_y_avisa():
    dictamen = {"clasificacion": "normalizacion", "sinActas": True, "seccionesForzadas": {"celda": True}}

    resultado = analizar_alcance_provisional(SheetsClientFalso(), object(), "CO9999999999", dictamen, None, [])

    assert resultado["spec"] == {}  # sin acta, sin hoja maestra -> spec vacío
    assert resultado["diagnostico"]["tipo_medida_final"] is None
    assert any('"no leer actas"' in a for a in resultado["alertas"])


def test_cumple_no_propone_equipos_pero_si_arma_el_resto_del_contexto():
    resultado = analizar_alcance_provisional(SheetsClientFalso(), object(), "co0200002425", {"clasificacion": "cumple"}, _ACTA_RESULTADO, _FILAS_METABASE)

    assert resultado["propuesta"] == []
    assert "Cumple" in resultado["alertas"][-1] or "Cumple" in "".join(resultado["alertas"])
    assert resultado["equipos_actuales"]["tc"]["marca"] == "ATEL"
