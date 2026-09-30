"""Regla del Descargo (columna I de la hoja OPEX): montaje de TCs/TPs, interior o exterior; $8M
para todos los OR salvo ENEL ($12M)."""

from core.services.carro_canasta import es_montaje_tc_tp
from core.services.descargo import indice_fila_descargo, valor_descargo


def test_montaje_tcs_y_tps_en_cualquier_ubicacion_aplican():
    for nombre in (
        "Montaje  TCs MT (1–3) – interior", "Montaje  TPs MT (1–3) – interior",
        "Montaje  TCs MT (1–3) – exterior", "Montaje  TPs MT (1–3) – exterior",
    ):
        assert es_montaje_tc_tp(nombre), nombre


def test_lo_que_no_es_montaje_de_tcs_o_tps_no_aplica():
    for nombre in (
        "Desmonte  TCs MT (1–3) – interior", "Desmonte  TPs MT (1–3) – exterior",
        # Menciona "Montaje TCs/TPs MT" solo para aclarar que NO lo incluye:
        "Instalación indirecta exterior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)",
        "Instalación indirecta interior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)",
        "Instalación TCs semidirecta (1 a 3 TCs)", "Retiro TCs semidirecta (1 a 3 TCs)",
        "Cambio de DPS (unidad)", "Calibración en sitio por equipo TCs - TPs MT", "", None,
    ):
        assert not es_montaje_tc_tp(nombre), nombre


def test_valor_por_operador():
    assert valor_descargo("ENEL") == 12_000_000
    assert valor_descargo("ENEL COLOMBIA") == 12_000_000  # texto crudo del OR, sin normalizar
    for operador in ("AFINIA", "EMCALI", "AIRE", "ESSA", "CELSIA VALLE", "ELECTROHUILA", "OTROS_OR", "EPM ANTIOQUIA", "", None):
        assert valor_descargo(operador) == 8_000_000, operador


def test_indice_es_la_primera_fila_de_montaje():
    maniobras = [
        "Instalación indirecta interior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)",
        "Montaje  TCs MT (1–3) – interior",
        "Montaje  TPs MT (1–3) – exterior",
    ]
    assert indice_fila_descargo(maniobras) == 1


def test_indice_none_sin_montaje():
    assert indice_fila_descargo(["Desmonte  TCs MT (1–3) – exterior", "Cambio de DPS (unidad)"]) is None
    assert indice_fila_descargo([]) is None
