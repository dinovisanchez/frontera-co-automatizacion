"""Escribe la propuesta de mano de obra (OPEX) ya confirmada en la hoja "OPEX".

Columnas reales confirmadas el 2026-09-22: A=CO, B=(vacía), C=Operador, D=Maniobra,
E=Cantidad, F:M=fórmulas (Costo Unitario MO, Costo total MO, Carro canasta, Descargo,
Acompañamiento, Costo total con extras, -10%, -20%) — la hoja las calcula sola a partir de
Maniobra/Operador/Cantidad, nunca se escriben directo. Además, a la derecha (columnas Q:S) hay
una tabla de referencia de OR/Valor de descargo/Acompañamiento — NO relacionada con la fila de
este CO (misma hoja, tabla aparte) — por eso acá NUNCA se inserta una fila completa (eso
desplazaría esa tabla): se escribe en la siguiente fila ya en blanco, copiando solo A:M desde
la fila anterior para heredar las fórmulas.

ÚNICA excepción a "las fórmulas nunca se escriben": la columna H (Carro canasta) lleva un valor
FIJO cuando el CO tiene montaje de TCs/TPs en exterior (ver carro_canasta.py) — UNA sola vez por
CO. Como esa celda deja de ser fórmula, la fila SIGUIENTE (que se crea copiando la anterior)
heredaría el valor fijo y lo duplicaría: por eso, en toda fila que no lleve el carro canasta, se
restaura la fórmula de H desde la última fila que aún la tiene.
"""

from core.data_sources.sheets_client import SheetsClient
from config.settings import CARRO_CANASTA_MONTAJE_EXTERIOR, SHEET_OPEX
from core.services.carro_canasta import indice_fila_carro_canasta

_NUM_COLUMNAS_FORMULA_OPEX = 13  # A:M — N/O/P son espaciadores, Q:S son la tabla de referencia aparte
_COL_CARRO_CANASTA = 8  # H (1-indexado)


def _es_formula(celda) -> bool:
    return isinstance(celda, str) and celda.startswith("=")


def _es_valor_fijo(celda) -> bool:
    """Celda con algo escrito que NO es fórmula (ej. el 4.500.000 de un CO anterior)."""
    return celda not in (None, "") and not _es_formula(celda)


def guardar_filas_opex(sheets: SheetsClient, co_raw: str, operador: str, filas: list[dict]) -> dict:
    """`filas`: [{"maniobra": str, "cantidad": float}, ...] — el costo lo calcula la hoja.

    Devuelve `carro_canasta`: {"fila", "maniobra", "valor"} de la fila que lo recibió, o None.
    """
    if not filas:
        raise ValueError("No hay filas para guardar.")

    hoja = sheets.hoja_por_nombre(SHEET_OPEX)
    ultima_fila_con_datos = len(hoja.col_values(1))  # última fila con algo en A, sin contar el grid vacío de relleno

    idx_carro = indice_fila_carro_canasta([f["maniobra"] for f in filas])

    # Columna H con sus fórmulas (no el valor calculado) para saber si la fila origen todavía
    # tiene la fórmula de Carro canasta o quedó con un valor fijo de un CO anterior.
    columna_h = hoja.col_values(_COL_CARRO_CANASTA, value_render_option="FORMULA")
    fila_formula_h = next((n for n in range(len(columna_h), 0, -1) if _es_formula(columna_h[n - 1])), None)
    h_origen_fijo = ultima_fila_con_datos <= len(columna_h) and _es_valor_fijo(columna_h[ultima_fila_con_datos - 1])

    guardadas = []
    carro_canasta = None
    fila_base = ultima_fila_con_datos
    for i, f in enumerate(filas):
        fila_nueva = fila_base + 1
        if fila_base > 1:
            sheets.copiar_fila(hoja, fila_origen=fila_base, fila_destino=fila_nueva, num_columnas=_NUM_COLUMNAS_FORMULA_OPEX)
        valores_fila = [co_raw, "", operador, f["maniobra"], f.get("cantidad", 1)]
        hoja.update(f"A{fila_nueva}:E{fila_nueva}", [valores_fila], value_input_option="USER_ENTERED")
        guardadas.append(valores_fila)

        if i == idx_carro:
            hoja.update([[CARRO_CANASTA_MONTAJE_EXTERIOR]], range_name=f"H{fila_nueva}", value_input_option="USER_ENTERED")
            carro_canasta = {"fila": fila_nueva, "maniobra": f["maniobra"], "valor": CARRO_CANASTA_MONTAJE_EXTERIOR}
            h_origen_fijo = True
        else:
            if fila_base > 1 and h_origen_fijo:
                # La copia de arriba trajo el valor fijo de la fila anterior — se restaura la fórmula.
                if fila_formula_h is not None:
                    sheets.copiar_fila(hoja, fila_origen=fila_formula_h, fila_destino=fila_nueva,
                                       num_columnas=_COL_CARRO_CANASTA, col_inicio=_COL_CARRO_CANASTA - 1)
                else:
                    hoja.update([[""]], range_name=f"H{fila_nueva}", value_input_option="USER_ENTERED")
            h_origen_fijo = False
        fila_base = fila_nueva

    return {"guardadas": guardadas, "hoja_url": hoja.url, "carro_canasta": carro_canasta}
