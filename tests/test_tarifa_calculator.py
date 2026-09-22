"""OPEX: normalización de operador, fuzzy-match filtrado por categoría (evita la colisión
real del caso CO0100002908) y detección de maniobras TC/TP en MT."""

from core.services import tarifa_calculator as tc

MANIOBRAS_DE_PRUEBA = [
    "Instalación de condensador/banco",
    "Instalación de medidor",
    "Instalación de transformador de corriente (TCs) en MT",
    "Instalación de transformador de potencial (TPs) en MT",
    "Retiro de medidor",
    "Montaje de celda de medida",
]


def test_normalizar_operador_tarifario_por_contencion():
    assert tc.normalizar_operador_tarifario("AFINIA CARIBE_MAR") == "AFINIA"
    assert tc.normalizar_operador_tarifario("Electrohuila S.A.") != "OTROS_OR"
    assert tc.normalizar_operador_tarifario("Un operador que no existe") == "OTROS_OR"


def test_buscar_maniobra_filtrada_evita_colision_entre_categorias():
    """Sin el filtro por palabra clave, "Instalación de medidor"/"...TC"/"...TP" fuzzy-matchean
    todas contra "Instalación de condensador/banco" (mismo bug real, CO0100002908)."""
    match_medidor = tc.buscar_maniobra_filtrada(MANIOBRAS_DE_PRUEBA, tc.PALABRAS_CLAVE_POR_CATEGORIA_OPEX["medidor"], tc.QUERY_MANIOBRA_POR_CATEGORIA_OPEX["medidor"])
    match_tc = tc.buscar_maniobra_filtrada(MANIOBRAS_DE_PRUEBA, tc.PALABRAS_CLAVE_POR_CATEGORIA_OPEX["tc"], tc.QUERY_MANIOBRA_POR_CATEGORIA_OPEX["tc"])

    assert match_medidor == "Instalación de medidor"
    assert match_tc == "Instalación de transformador de corriente (TCs) en MT"
    assert match_medidor != match_tc  # antes del fix, ambas colapsaban en la misma maniobra


def test_buscar_maniobra_filtrada_sin_candidatos_devuelve_none():
    assert tc.buscar_maniobra_filtrada(MANIOBRAS_DE_PRUEBA, ["bloque"], "Instalación de bloque de pruebas") is None


def test_categoria_desde_grupo_opex():
    assert tc.categoria_desde_grupo_opex("TC") == "tc"
    assert tc.categoria_desde_grupo_opex("Transformador de Potencial") == "tp"
    assert tc.categoria_desde_grupo_opex("Cable señal") == "cable"
    assert tc.categoria_desde_grupo_opex("algo desconocido") is None


def test_es_maniobra_tc_tp_mt():
    assert tc.es_maniobra_tc_tp_mt("Montaje de TCs en MT") is True
    assert tc.es_maniobra_tc_tp_mt("Instalación de transformador de corriente (TCs) en MT") is False  # sin "montaje/desmonte" no cuenta
    assert tc.es_maniobra_tc_tp_mt("Instalación de medidor") is False


def test_contraparte_instalar_desinstalar():
    contraparte = tc.contraparte_instalar_desinstalar("Instalación de medidor", MANIOBRAS_DE_PRUEBA)
    assert contraparte == "Retiro de medidor"
