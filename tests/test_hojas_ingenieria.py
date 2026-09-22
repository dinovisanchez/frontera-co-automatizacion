"""Hojas de ingeniería con un SheetsClient falso — sin credenciales reales de Google.

El foco es el fix del bug real de "Propiedad de Activos": los valores reales de la hoja
maestra son "OR" y "Usuario", no "Exclusivo"/"Compartido" — confirmado leyendo la hoja en
vivo el 2026-09-22 (columna L de BD_Telemedida).
"""

from core.services.hojas_ingenieria import _propiedad_activos_a_uso, buscar_en_hoja_maestra
from config.settings import CONTROL_SHEET_ID, MAESTRO_GID


def test_propiedad_activos_or_es_compartido():
    assert _propiedad_activos_a_uso("OR") == "compartido"


def test_propiedad_activos_usuario_es_exclusivo():
    assert _propiedad_activos_a_uso("Usuario") == "exclusivo"


def test_propiedad_activos_literales_tambien_funcionan():
    assert _propiedad_activos_a_uso("Compartida") == "compartido"
    assert _propiedad_activos_a_uso("Exclusivo") == "exclusivo"


def test_propiedad_activos_valor_desconocido_es_none():
    assert _propiedad_activos_a_uso("algo raro") is None
    assert _propiedad_activos_a_uso(None) is None


class HojaFalsa:
    id = MAESTRO_GID
    row_count = 10


class SheetsClientFalso:
    """Solo implementa lo que hojas_ingenieria.py necesita para la hoja maestra."""

    def __init__(self, header: list[str], fila: list):
        self._header = header
        self._fila = fila

    def hoja_externa_por_gid(self, spreadsheet_id: str, gid: int):
        assert spreadsheet_id == CONTROL_SHEET_ID
        assert gid == MAESTRO_GID
        return HojaFalsa()

    def leer_todo(self, hoja, sin_formato: bool = False):
        return [self._header, self._fila]


def test_buscar_en_hoja_maestra_usa_el_fix_or_usuario():
    header = ["ID Interno", "OR", "Nivel de tension", "Propiedad de Activos", "Factor Fx", "Capacidad Transformador", "conexion", "medida"]
    fila = ["CO0200002425", "EMCALI CALI", "1", "OR", 40, 300, "Trifasica", "Semidirecta"]
    sheets = SheetsClientFalso(header, fila)

    maestro = buscar_en_hoja_maestra(sheets, "CO0200002425")

    assert maestro["propiedad_activos"] == "compartido"  # antes del fix esto habría quedado en None
    assert maestro["medida"] == "semidirecta"
    assert maestro["elementos"] == 3
    assert maestro["factor_fx"] == 40
    assert maestro["capacidad_transformador"] == 300


def test_buscar_en_hoja_maestra_co_no_encontrado():
    sheets = SheetsClientFalso(["ID Interno"], ["CO_OTRO"])
    assert buscar_en_hoja_maestra(sheets, "CO0200002425") is None
