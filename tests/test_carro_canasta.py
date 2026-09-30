"""Regla del Carro canasta (columna H de la hoja OPEX) — detección de "Montaje TCs/TPs MT exterior"."""

from core.services.carro_canasta import es_montaje_tc_tp_exterior, indice_fila_carro_canasta


def test_montaje_tcs_y_tps_exterior_si_aplican():
    assert es_montaje_tc_tp_exterior("Montaje  TCs MT (1–3) – exterior")
    assert es_montaje_tc_tp_exterior("Montaje  TPs MT (1–3) – exterior")


def test_montaje_interior_no_aplica():
    assert not es_montaje_tc_tp_exterior("Montaje  TCs MT (1–3) – interior")
    assert not es_montaje_tc_tp_exterior("Montaje  TPs MT (1–3) – interior")


def test_desmonte_exterior_no_aplica():
    assert not es_montaje_tc_tp_exterior("Desmonte  TCs MT (1–3) – exterior")
    assert not es_montaje_tc_tp_exterior("Desmonte  TPs MT (1–3) – exterior")


def test_instalacion_que_solo_menciona_montaje_para_aclarar_que_no_lo_incluye_no_aplica():
    # Trampa real de ref_tarifario: contiene "exterior", "Montaje", "TCs" y "TPs", pero es la
    # instalación del medidor+BP — no un montaje de TCs/TPs.
    assert not es_montaje_tc_tp_exterior("Instalación indirecta exterior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)")
    assert not es_montaje_tc_tp_exterior("Retiro indirecta exterior: medidor + BP + módem (sin retiro TCs/TPs MT)")


def test_instalacion_tcs_semidirecta_no_aplica():
    assert not es_montaje_tc_tp_exterior("Instalación TCs semidirecta (1 a 3 TCs)")


def test_vacio_o_none_no_aplica():
    assert not es_montaje_tc_tp_exterior(None)
    assert not es_montaje_tc_tp_exterior("")


def test_indice_es_la_primera_fila_de_montaje_exterior():
    maniobras = [
        "Instalación indirecta exterior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)",
        "Montaje  TCs MT (1–3) – exterior",
        "Montaje  TPs MT (1–3) – exterior",
    ]
    assert indice_fila_carro_canasta(maniobras) == 1


def test_indice_none_si_no_hay_montaje_exterior():
    assert indice_fila_carro_canasta(["Montaje  TCs MT (1–3) – interior", "Cambio de DPS (unidad)"]) is None
    assert indice_fila_carro_canasta([]) is None
