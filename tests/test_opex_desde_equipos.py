"""opex_desde_equipos.py con un tarifario falso (maniobras reales verificadas + precios de
prueba) — sin Google Sheets real."""

from core.services import opex_desde_equipos as oe
from core.services import tarifa_calculator as tc
from tests.test_tarifa_calculator import MANIOBRAS_REALES


def _tarifario_falso():
    return {"maniobras": MANIOBRAS_REALES, "precios": {m: {"AFINIA": 100000.0, "OTROS_OR": 50000.0} for m in MANIOBRAS_REALES}}


def test_indirecta_interior_instalacion_nueva_con_tc_y_tp(monkeypatch):
    monkeypatch.setattr(tc, "obtener_ref_tarifario_cacheado", lambda sheets: _tarifario_falso())

    resultado = oe.construir_opex_desde_equipos(
        sheets=None, co="CO0100002908", or_raw="AFINIA",
        tipo_medida_final="indirecta", ubicacion="interior",
        secciones={"medidor": True, "tc": True, "tp": True, "bloque_pruebas": True},
        es_instalacion_nueva=True,
    )

    nombres = {f["maniobra"] for f in resultado.filas}
    assert "Instalación indirecta interior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)" in nombres
    assert "Montaje  TCs MT (1–3) – interior" in nombres
    assert "Montaje  TPs MT (1–3) – interior" in nombres
    assert "Apertura de portacircuito (unidad)" in nombres
    assert "Cambio de DPS (unidad)" in nombres  # instalación nueva -> DPS, no calibración
    # instalación nueva: NO debe traer ningún "Retiro"/"Desmonte", ni "Revisión de frontera"
    # (esa solo aplica cuando es un cambio — Dinovi, 2026-09-22)
    assert not any("retiro" in n.lower() or "desmonte" in n.lower() for n in nombres)
    assert "Revisión de frontera con OR u otro agente (acompañamiento y registro)" not in nombres
    # "Cambio de crucetas en MT (exterior)" es SOLO para exterior, esto es interior
    assert "Cambio de crucetas en MT (exterior)(unidad)" not in nombres
    assert resultado.alertas == []


def test_indirecta_exterior_cambio_de_equipo_agrega_desmonte(monkeypatch):
    monkeypatch.setattr(tc, "obtener_ref_tarifario_cacheado", lambda sheets: _tarifario_falso())

    resultado = oe.construir_opex_desde_equipos(
        sheets=None, co="CO0100002908", or_raw="AFINIA",
        tipo_medida_final="indirecta", ubicacion="exterior",
        secciones={"medidor": True, "tc": True, "tp": False, "bloque_pruebas": True},
        es_instalacion_nueva=False,
    )

    nombres = {f["maniobra"] for f in resultado.filas}
    assert "Retiro indirecta exterior: medidor + BP + módem (sin retiro TCs/TPs MT)" in nombres
    assert "Desmonte  TCs MT (1–3) – exterior" in nombres
    assert "Calibración en sitio por equipo TCs - TPs MT" in nombres  # cambio -> calibración, no DPS
    assert "Cambio de DPS (unidad)" not in nombres
    assert not any("tps" in n.lower() and "montaje" in n.lower() for n in nombres)  # tp=False, no debe aparecer
    # Es un cambio -> el OR debe estar presente (Dinovi, 2026-09-22)
    assert "Revisión de frontera con OR u otro agente (acompañamiento y registro)" in nombres
    # Indirecta EXTERIOR -> cambio de crucetas en MT (Dinovi, 2026-09-22)
    assert "Cambio de crucetas en MT (exterior)(unidad)" in nombres


def test_semidirecta_cambio_de_tc_agrega_revision_de_frontera_sin_extras_mt(monkeypatch):
    """Caso real CO0200002425 (2026-09-22): semidirecta, TC ya instalado sin certificado ->
    se cambia (retiro+instalación). Es un cambio, así que debe salir "Revisión de frontera
    con OR" — pero NO los extras de MT (apertura de portacircuito/crucetas/DPS/calibración),
    porque las TCs de semidirecta no son de Media Tensión.
    """
    monkeypatch.setattr(tc, "obtener_ref_tarifario_cacheado", lambda sheets: _tarifario_falso())

    resultado = oe.construir_opex_desde_equipos(
        sheets=None, co="CO0200002425", or_raw="EMCALI CALI",
        tipo_medida_final="semidirecta", ubicacion="interior",
        secciones={"medidor": False, "tc": True, "bloque_pruebas": False, "celda": True},
        es_instalacion_nueva=False,
    )

    nombres = {f["maniobra"] for f in resultado.filas}
    assert nombres == {
        "Instalación TCs semidirecta (1 a 3 TCs)",
        "Retiro TCs semidirecta (1 a 3 TCs)",
        "Revisión de frontera con OR u otro agente (acompañamiento y registro)",
    }
    assert resultado.operador == "EMCALI"
    assert any("celda" in a.lower() for a in resultado.alertas)


def test_semidirecta_solo_medidor_sin_bloque(monkeypatch):
    monkeypatch.setattr(tc, "obtener_ref_tarifario_cacheado", lambda sheets: _tarifario_falso())

    resultado = oe.construir_opex_desde_equipos(
        sheets=None, co="CO0100002908", or_raw="AFINIA",
        tipo_medida_final="semidirecta", ubicacion="interior",
        secciones={"medidor": True, "tc": False, "bloque_pruebas": False},
        es_instalacion_nueva=True,
    )

    nombres = {f["maniobra"] for f in resultado.filas}
    assert "Instalación medidor semidirecta interior (incluye cambio módem si aplica)" in nombres
    assert "Instalación semidirecta interior (medidor + bloque + módem + toma 110V si aplica)" not in nombres


def test_directa_no_agrega_nada_de_tc_tp(monkeypatch):
    monkeypatch.setattr(tc, "obtener_ref_tarifario_cacheado", lambda sheets: _tarifario_falso())

    resultado = oe.construir_opex_desde_equipos(
        sheets=None, co="CO0100002908", or_raw="AFINIA",
        tipo_medida_final="directa", ubicacion="exterior",
        secciones={"medidor": True, "tc": False, "tp": False, "bloque_pruebas": False},
        es_instalacion_nueva=True,
    )

    nombres = {f["maniobra"] for f in resultado.filas}
    assert nombres == {"Instalación medida directa exterior (medidor + módem + toma 110V si aplica)"}


def test_celda_sin_maniobra_queda_como_alerta(monkeypatch):
    monkeypatch.setattr(tc, "obtener_ref_tarifario_cacheado", lambda sheets: _tarifario_falso())

    resultado = oe.construir_opex_desde_equipos(
        sheets=None, co="CO0100002908", or_raw="AFINIA",
        tipo_medida_final="indirecta", ubicacion="interior",
        secciones={"medidor": False, "tc": False, "tp": False, "bloque_pruebas": False, "celda": True},
        es_instalacion_nueva=True,
    )

    assert any("celda" in a.lower() for a in resultado.alertas)
    assert resultado.filas == []
