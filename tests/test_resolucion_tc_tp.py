"""Búsqueda de candidatos TC + reglas por operador — sin credenciales reales."""

from core.services.catalogo_capex import parsear_tc
from core.services.resolucion_tc_tp import buscar_candidatos_tc, es_or_epm, inferir_ubicacion_por_or, preferir_con_cable_por_or

_CATALOGO_TC = [
    {"sku": "TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV", "categoria": "Transformador de corriente", "costo": 123000.0, "tc": parsear_tc("TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV")},
    {"sku": "TC 200/5 Ventana Exterior C 0.5s B 5 VA T 0.72 kV", "categoria": "Transformador de corriente", "costo": 162400.0, "tc": parsear_tc("TC 200/5 Ventana Exterior C 0.5s B 5 VA T 0.72 kV")},
    {"sku": "TC 200/5 Ventana Exterior Con cable C 0.5s B 5 VA T 0.72 kV", "categoria": "Transformador de corriente", "costo": 120000.0, "tc": parsear_tc("TC 200/5 Ventana Exterior Con cable C 0.5s B 5 VA T 0.72 kV")},
]


def test_preferir_con_cable_solo_emcali():
    assert preferir_con_cable_por_or("EMCALI CALI") is True
    assert preferir_con_cable_por_or("ENEL CUNDINAMARCA") is False


def test_es_or_epm():
    assert es_or_epm("EPM ANTIOQUIA") is True
    assert es_or_epm("EMCALI CALI") is False


def test_inferir_ubicacion_por_or_solo_aire():
    assert inferir_ubicacion_por_or("AIRE CARIBE_SOL", "") == "exterior"
    assert inferir_ubicacion_por_or("Air-e", "instalado en el Centro Comercial Único") == "interior"
    assert inferir_ubicacion_por_or("EMCALI", "") is None


def test_buscar_candidatos_tc_prioriza_ubicacion_correcta():
    candidatos = buscar_candidatos_tc(_CATALOGO_TC, "200/5", "interior", 0.72)
    assert candidatos[0]["sku"] == "TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV"


def test_buscar_candidatos_tc_preferir_con_cable_filtra_cuando_hay_opcion():
    candidatos = buscar_candidatos_tc(_CATALOGO_TC, "200/5", "exterior", 0.72, preferir_con_cable=True)
    assert candidatos[0]["sku"] == "TC 200/5 Ventana Exterior Con cable C 0.5s B 5 VA T 0.72 kV"


def test_buscar_candidatos_tc_burden_incorrecto_se_descarta():
    candidatos = buscar_candidatos_tc(_CATALOGO_TC, "200/5", "interior", 0.72, burden_requerido=2.5)
    assert candidatos == []
