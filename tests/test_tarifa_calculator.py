"""OPEX: normalización de operador y el matcher por palabras clave (buscar_maniobra_por_palabras)
contra un extracto de las maniobras REALES de ref_tarifario (gid 192919919, verificado
2026-09-21) — no plantillas inventadas.
"""

from core.services import tarifa_calculator as tc

MANIOBRAS_REALES = [
    "Instalación medida directa exterior (medidor + módem + toma 110V si aplica)",
    "Instalación medida directa interior (medidor + módem + toma 110V si aplica)",
    "Retiro medida directa interior (medidor)",
    "Retiro medida directa exterior (medidor)",
    "Instalación semidirecta exterior (medidor + bloque + módem + toma 110V si aplica)",
    "Instalación semidirecta interior (medidor + bloque + módem + toma 110V si aplica)",
    "Retiro semidirecta (medidor + bloque + módem) – sin desenergización",
    "Instalación medidor semidirecta interior (incluye cambio módem si aplica)",
    "Instalación medidor semidirecta exterior (incluye cambio módem si aplica)",
    "Retiro medidor semidirecta interior",
    "Retiro medidor semidirecta exterior",
    "Instalación TCs semidirecta (1 a 3 TCs)",
    "Retiro TCs semidirecta (1 a 3 TCs)",
    "Instalación indirecta interior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)",
    "Instalación indirecta exterior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)",
    "Retiro indirecta interior: medidor + BP + módem (sin retiro TCs/TPs MT)",
    "Retiro indirecta exterior: medidor + BP + módem (sin retiro TCs/TPs MT)",
    "Desmonte  TCs MT (1–3) – exterior",
    "Desmonte  TPs MT (1–3) – exterior",
    "Desmonte  TCs MT (1–3) – interior",
    "Desmonte  TPs MT (1–3) – interior",
    "Montaje  TCs MT (1–3) – exterior",
    "Montaje  TPs MT (1–3) – exterior",
    "Montaje  TCs MT (1–3) – interior",
    "Montaje  TPs MT (1–3) – interior",
    "Apertura de portacircuito (unidad)",
    "Revisión de frontera con OR u otro agente (acompañamiento y registro)",
    "Cambio de crucetas en MT (exterior)(unidad)",
    "Cambio de DPS (unidad)",
    "Calibración en sitio por equipo TCs - TPs MT",
]


def test_normalizar_operador_tarifario_por_contencion():
    assert tc.normalizar_operador_tarifario("AFINIA CARIBE_MAR") == "AFINIA"
    assert tc.normalizar_operador_tarifario("Electrohuila S.A.") != "OTROS_OR"
    assert tc.normalizar_operador_tarifario("Un operador que no existe") == "OTROS_OR"


def test_distingue_interior_de_exterior():
    interior = tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["instalacion", "medida", "directa", "interior"])
    exterior = tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["instalacion", "medida", "directa", "exterior"])
    assert interior == "Instalación medida directa interior (medidor + módem + toma 110V si aplica)"
    assert exterior == "Instalación medida directa exterior (medidor + módem + toma 110V si aplica)"
    assert interior != exterior


def test_distingue_bundle_con_bloque_de_medidor_solo():
    """El caso que rompía el fuzzy-match genérico: "medidor semidirecta interior" aparece en
    AMBAS maniobras (con y sin bloque) — solo la palabra clave + la exclusión desambiguan."""
    con_bloque = tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["instalacion", "semidirecta", "bloque", "interior"])
    sin_bloque = tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["instalacion", "medidor", "semidirecta", "interior"], excluidas=["bloque"])

    assert con_bloque == "Instalación semidirecta interior (medidor + bloque + módem + toma 110V si aplica)"
    assert sin_bloque == "Instalación medidor semidirecta interior (incluye cambio módem si aplica)"


def test_montaje_desmonte_tc_tp_mt_por_ubicacion():
    assert tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["montaje", "tcs", "mt", "interior"]) == "Montaje  TCs MT (1–3) – interior"
    assert tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["desmonte", "tps", "mt", "exterior"]) == "Desmonte  TPs MT (1–3) – exterior"


def test_retiro_semidirecta_bundle_sin_variante_de_ubicacion():
    """Esta maniobra NO tiene variante interior/exterior en la hoja real — una sola línea."""
    assert tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["retiro", "semidirecta", "bloque"]) == "Retiro semidirecta (medidor + bloque + módem) – sin desenergización"


def test_extra_fija_mt():
    assert tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["apertura", "portacircuito"]) == "Apertura de portacircuito (unidad)"
    assert tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["calibracion", "sitio", "tcs", "tps", "mt"]) == "Calibración en sitio por equipo TCs - TPs MT"


def test_sin_match_o_ambiguo_devuelve_none():
    assert tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["esto", "no", "existe"]) is None
    # "instalacion" + "semidirecta" solas son ambiguas (matchean 2 maniobras: con y sin bloque)
    assert tc.buscar_maniobra_por_palabras(MANIOBRAS_REALES, ["instalacion", "semidirecta", "interior"]) is None


def test_categoria_desde_grupo_opex():
    assert tc.categoria_desde_grupo_opex("TC") == "tc"
    assert tc.categoria_desde_grupo_opex("Transformador de Potencial") == "tp"
    assert tc.categoria_desde_grupo_opex("Cable señal") == "cable"
    assert tc.categoria_desde_grupo_opex("algo desconocido") is None
