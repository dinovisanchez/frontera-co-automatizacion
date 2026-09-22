"""Escribe la propuesta de mano de obra (OPEX) ya confirmada en la hoja "OPEX".

Columnas reales confirmadas el 2026-09-22: A=CO, B=(vacía), C=Operador, D=Maniobra,
E=Cantidad, F:M=fórmulas (Costo Unitario MO, Costo total MO, Carro canasta, Descargo,
Acompañamiento, Costo total con extras, -10%, -20%) — la hoja las calcula sola a partir de
Maniobra/Operador/Cantidad, nunca se escriben directo. Además, a la derecha (columnas Q:S) hay
una tabla de referencia de OR/Valor de descargo/Acompañamiento — NO relacionada con la fila de
este CO (misma hoja, tabla aparte) — por eso acá NUNCA se inserta una fila completa (eso
desplazaría esa tabla): se escribe en la siguiente fila ya en blanco, copiando solo A:M desde
la fila anterior para heredar las fórmulas.
"""

from core.data_sources.sheets_client import SheetsClient
from config.settings import SHEET_OPEX

_NUM_COLUMNAS_FORMULA_OPEX = 13  # A:M — N/O/P son espaciadores, Q:S son la tabla de referencia aparte


def guardar_filas_opex(sheets: SheetsClient, co_raw: str, operador: str, filas: list[dict]) -> dict:
    """`filas`: [{"maniobra": str, "cantidad": float}, ...] — el costo lo calcula la hoja."""
    if not filas:
        raise ValueError("No hay filas para guardar.")

    hoja = sheets.hoja_por_nombre(SHEET_OPEX)
    ultima_fila_con_datos = len(hoja.col_values(1))  # última fila con algo en A, sin contar el grid vacío de relleno

    guardadas = []
    fila_base = ultima_fila_con_datos
    for f in filas:
        fila_nueva = fila_base + 1
        if fila_base > 1:
            sheets.copiar_fila(hoja, fila_origen=fila_base, fila_destino=fila_nueva, num_columnas=_NUM_COLUMNAS_FORMULA_OPEX)
        valores_fila = [co_raw, "", operador, f["maniobra"], f.get("cantidad", 1)]
        hoja.update(f"A{fila_nueva}:E{fila_nueva}", [valores_fila], value_input_option="USER_ENTERED")
        guardadas.append(valores_fila)
        fila_base = fila_nueva

    return {"guardadas": guardadas, "hoja_url": hoja.url}
