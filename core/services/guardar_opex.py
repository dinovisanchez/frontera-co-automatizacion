"""Escribe la propuesta de mano de obra (OPEX) ya confirmada en la hoja "OPEX".

A diferencia de "Equipos", esta hoja NO tiene columna de código CO (confirmado por Dinovi,
2026-09-22), así que no hay forma de ubicar "las filas de este CO" para insertar debajo —
las filas nuevas siempre se agregan al final.
"""

from core.data_sources.sheets_client import SheetsClient
from config.settings import SHEET_OPEX


def guardar_filas_opex(sheets: SheetsClient, filas: list[dict]) -> dict:
    """`filas`: [{"maniobra": str, "cantidad": float, "costo_unitario": float,
    "costo_total": float}, ...] — mismo orden de columnas que ya usa el botón de copiar."""
    if not filas:
        raise ValueError("No hay filas para guardar.")

    hoja = sheets.hoja_por_nombre(SHEET_OPEX)
    valores = [
        [f["maniobra"], f.get("cantidad", 1), f.get("costo_unitario", 0), f.get("costo_total", 0)]
        for f in filas
    ]
    hoja.append_rows(valores, value_input_option="USER_ENTERED")

    return {"guardadas": valores, "hoja_url": hoja.url}
