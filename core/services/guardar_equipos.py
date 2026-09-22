"""Escribe la propuesta ya confirmada por el usuario en la hoja "Equipos" — puerto de
guardarAlcanceProvisional (Codigo.gs). Inserta las filas nuevas justo debajo de las filas que
ya existan para este CO (mismo criterio que "encontrar el código y pegar cada uno debajo del
otro"); si el CO no tiene ninguna fila previa ahí, las agrega al final de la hoja.
"""

from core.data_sources.sheets_client import SheetsClient
from core.services.hoja_origen_equipos import leer_equipos_existentes, leer_origen_alcance
from core.utils import normalizar_codigo
from config.settings import SHEET_EQUIPOS


def guardar_filas_equipos(sheets: SheetsClient, co_raw: str, filas: list[dict]) -> dict:
    """`filas`: [{"sku": str, "cantidad": int, "tipo": str}, ...] — ya filtradas/confirmadas
    por el usuario (sin las que marcó "excluir"). cliente/OR/maniobra se toman de la hoja
    "Data" (leer_origen_alcance), igual que hacía el original: el usuario nunca los escribe
    a mano en esta pantalla.
    """
    co = normalizar_codigo(co_raw)
    if not filas:
        raise ValueError("No hay filas para guardar.")

    origen = leer_origen_alcance(sheets, co)
    existentes = leer_equipos_existentes(sheets, co)
    hoja = sheets.hoja_por_nombre(SHEET_EQUIPOS)

    valores = [
        [co, origen["cliente"], origen["or"], origen["maniobra"], f["sku"], f.get("cantidad", 1), f.get("tipo", "")]
        for f in filas
    ]

    ultima_fila_existente = max((f["fila"] for f in existentes), default=None)
    if ultima_fila_existente is not None:
        hoja.insert_rows(valores, row=ultima_fila_existente + 1, value_input_option="USER_ENTERED")
    else:
        hoja.append_rows(valores, value_input_option="USER_ENTERED")

    return {"guardadas": valores, "hoja_url": hoja.url}
