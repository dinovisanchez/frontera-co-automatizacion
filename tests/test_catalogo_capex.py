"""Parseo de SKUs de ref_capex (texto libre) — verificado contra ítems reales del catálogo."""

from core.services.catalogo_capex import normalizar_sku_contra_catalogo, parsear_medidor, parsear_tc, parsear_tp


def test_parsear_tc_caso_real_co0200002425():
    """SKU real encontrado en ref_capex para el TC de CO0200002425 (200/5, ventana interior, BT)."""
    info = parsear_tc("TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV")
    assert info["ratio"] == "200/5"
    assert info["ubicacion"] == "interior"
    assert info["burden"] == 5.0
    assert info["kv"] == 0.72
    assert info["montaje"] == "ventana"


def test_parsear_tc_barra_pasante_con_cable():
    info = parsear_tc("TC 200/5 Ventana Exterior Con cable C 0.5s B 5 VA T 0.72 kV")
    assert info["con_cable"] is True
    assert info["ubicacion"] == "exterior"

    info2 = parsear_tc("TC 1000/5 Barra Pasante C 0.5s B 2.5 VA T 0.72 kV")
    assert info2["montaje"] == "barra_pasante"
    assert info2["con_cable"] is None


def test_parsear_tp_fase_neutro_sin_raiz():
    info = parsear_tp("TP 13200/120 V 5 VA Interior 17.5 kV")
    assert info["primario"] == 13200
    assert info["secundario"] == 120
    assert info["ubicacion"] == "interior"


def test_parsear_tp_bug_preexistente_raiz_3_corrompe_el_primario():
    """BUG PREEXISTENTE en Codigo.gs (no introducido por esta migración, se porta fiel):
    partes[0].replace(/[^\\d.]/g, '') solo quita el símbolo "√", pero el "3" de "√3" SÍ es un
    dígito — queda pegado al final del número ("13200√3" -> "132003" en vez de 13200).
    Confirmado con el mismo regex en el original; reportado a Dinovi. Esto hace que
    buscarCandidatosTP nunca encuentre estos ítems reales del catálogo (formato real visto en
    Normalizaciones_Indirectas: "TP 13200√3/120√3 V 5 VA Interior 17.5 kV").
    """
    info = parsear_tp("TP 13200√3/120√3 V 5 VA Interior 17.5 kV")
    assert info["primario"] == 132003  # valor corrompido, NO 13200 — documenta el bug, no lo "arregla"
    assert info["con_raiz_primario"] is True
    assert info["con_raiz_secundario"] is True
    assert info["ubicacion"] == "interior"


def test_parsear_medidor_dual_rated_semidirecta_e_indirecta():
    """Un ítem "Semidirecta / Indirecta" debe calzar con AMBOS tipos, no solo el primero que se
    pruebe — "directa" es substring literal de "indirecta", por eso hay que descartarlas antes
    de probar "directa" de forma independiente."""
    info = parsear_medidor("INHEMETER iT30 Semidirecta / Indirecta C0.5S 3×277/480V")
    assert "semidirecta" in info["tipos_medida"]
    assert "indirecta" in info["tipos_medida"]
    assert "directa" not in info["tipos_medida"]
    assert info["fases"] == 3


def test_parsear_medidor_modelos_inhemeter_directa():
    assert parsear_medidor("INHEMETER P2000D 160Cor10") == {"tipos_medida": ["directa"], "fases": 3}


def test_parsear_medidor_bug_preexistente_c2000_pegado_al_sufijo():
    """BUG PREEXISTENTE en Codigo.gs (no introducido por esta migración, se porta fiel):
    \\bC2000\\b / \\bD2000\\b exigen un borde de palabra DESPUÉS del código de modelo, pero los
    SKUs reales del catálogo (ej. "C2000Cor5 (100) AT", "D2000Cor5(100) AT") pegan el sufijo
    directamente sin espacio — dígito seguido de letra sigue siendo un solo "\\w", así que la
    regex nunca hace match ahí. Confirmado leyendo ref_capex el 2026-09-22; reportado a Dinovi
    para decidir si se corrige. Este test documenta el comportamiento ACTUAL (fiel al
    original), no lo "correcto" — si algún día se arregla el regex, este test debe cambiar.
    """
    assert parsear_medidor("C2000Cor5 (100) AT") == {"tipos_medida": [], "fases": None}
    assert parsear_medidor("D2000Cor5(100) AT") == {"tipos_medida": [], "fases": None}
    # Con un espacio antes del sufijo (o el modelo solo) SÍ matchea — confirma que el problema
    # es específicamente el borde de palabra, no la detección en general.
    assert parsear_medidor("C2000 Cor5 (100) AT") == {"tipos_medida": ["directa"], "fases": 1}


def test_normalizar_sku_contra_catalogo_exacto_y_por_similitud():
    catalogo = [
        {"sku": "TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV", "categoria": "Transformador de corriente"},
        {"sku": "Celda AE-325", "categoria": "Celda de medida"},
    ]
    assert normalizar_sku_contra_catalogo(catalogo, "Celda AE-325")["sku"] == "Celda AE-325"
    assert normalizar_sku_contra_catalogo(catalogo, "algo que no existe en ningún lado") is None
