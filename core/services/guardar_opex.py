"""Escribe la propuesta de mano de obra (OPEX) ya confirmada en la hoja "OPEX".

Columnas reales confirmadas el 2026-09-22: A=CO, B=(vacía), C=Operador, D=Maniobra,
E=Cantidad, F:M=fórmulas (Costo Unitario MO, Costo total MO, Carro canasta, Descargo,
Acompañamiento, Costo total con extras, -10%, -20%) — la hoja las calcula sola a partir de
Maniobra/Operador/Cantidad, nunca se escriben directo. Además, a la derecha (columnas Q:S) hay
una tabla de referencia de OR/Valor de descargo/Acompañamiento — NO relacionada con la fila de
este CO (misma hoja, tabla aparte) — por eso acá NUNCA se inserta una fila completa (eso
desplazaría esa tabla): se escribe en la siguiente fila ya en blanco, copiando solo A:M desde
la fila anterior para heredar las fórmulas.

ÚNICA excepción a "las fórmulas nunca se escriben": dos columnas llevan un valor FIJO, UNA sola vez
por CO, cuando el alcance trae montaje de TCs/TPs:
- H (Carro canasta): montaje exterior (ver carro_canasta.py).
- I (Descargo): montaje interior o exterior; el valor depende del OR (ver descargo.py).
Como esas celdas dejan de ser fórmula, la fila SIGUIENTE (que se crea copiando la anterior)
heredaría el valor fijo y lo duplicaría: por eso, en toda fila que no lleve ese valor, se
restaura la fórmula de la columna desde la última fila que aún la tiene (cada columna por separado).
"""

from core.data_sources.sheets_client import SheetsClient
from config.settings import CARRO_CANASTA_MONTAJE_EXTERIOR, SHEET_OPEX
from core.services.carro_canasta import indice_fila_carro_canasta
from core.services.descargo import indice_fila_descargo, valor_descargo

_NUM_COLUMNAS_FORMULA_OPEX = 13  # A:M — N/O/P son espaciadores, Q:S son la tabla de referencia aparte
_COL_CARRO_CANASTA = 8  # H (1-indexado)
_COL_DESCARGO = 9  # I
_LETRA_COLUMNA = {_COL_CARRO_CANASTA: "H", _COL_DESCARGO: "I"}


def _es_formula(celda) -> bool:
    return isinstance(celda, str) and celda.startswith("=")


def _es_valor_fijo(celda) -> bool:
    """Celda con algo escrito que NO es fórmula (ej. el 4.500.000 de un CO anterior)."""
    return celda not in (None, "") and not _es_formula(celda)


def _leer_columna_con_formulas(hoja, col: int, ultima_fila_con_datos: int) -> dict:
    """Estado de una columna que a veces lleva valor fijo: en qué fila está su fórmula (la última
    que aún la tiene) y si la fila origen de la copia (la última con datos) ya trae un valor fijo."""
    # value_render_option="FORMULA": hay que ver la fórmula, no el valor calculado.
    valores = hoja.col_values(col, value_render_option="FORMULA")
    fila_formula = next((n for n in range(len(valores), 0, -1) if _es_formula(valores[n - 1])), None)
    origen_fijo = ultima_fila_con_datos <= len(valores) and _es_valor_fijo(valores[ultima_fila_con_datos - 1])
    return {"fila_formula": fila_formula, "origen_fijo": origen_fijo}


def guardar_filas_opex(sheets: SheetsClient, co_raw: str, operador: str, filas: list[dict]) -> dict:
    """`filas`: [{"maniobra": str, "cantidad": float}, ...] — el costo lo calcula la hoja.

    Devuelve `carro_canasta` y `descargo`: {"fila", "maniobra", "valor"} de la fila que recibió
    cada uno, o None si el CO no lo lleva.
    """
    if not filas:
        raise ValueError("No hay filas para guardar.")

    hoja = sheets.hoja_por_nombre(SHEET_OPEX)
    ultima_fila_con_datos = len(hoja.col_values(1))  # última fila con algo en A, sin contar el grid vacío de relleno

    maniobras = [f["maniobra"] for f in filas]
    idx_por_columna = {_COL_CARRO_CANASTA: indice_fila_carro_canasta(maniobras), _COL_DESCARGO: indice_fila_descargo(maniobras)}
    valor_por_columna = {_COL_CARRO_CANASTA: CARRO_CANASTA_MONTAJE_EXTERIOR, _COL_DESCARGO: valor_descargo(operador)}
    columnas = {col: _leer_columna_con_formulas(hoja, col, ultima_fila_con_datos) for col in idx_por_columna}

    guardadas = []
    asignados: dict[int, dict | None] = {col: None for col in idx_por_columna}
    fila_base = ultima_fila_con_datos
    for i, f in enumerate(filas):
        fila_nueva = fila_base + 1
        if fila_base > 1:
            sheets.copiar_fila(hoja, fila_origen=fila_base, fila_destino=fila_nueva, num_columnas=_NUM_COLUMNAS_FORMULA_OPEX)
        valores_fila = [co_raw, "", operador, f["maniobra"], f.get("cantidad", 1)]
        hoja.update(f"A{fila_nueva}:E{fila_nueva}", [valores_fila], value_input_option="USER_ENTERED")
        guardadas.append(valores_fila)

        for col, estado in columnas.items():
            if i == idx_por_columna[col]:
                valor = valor_por_columna[col]
                hoja.update([[valor]], range_name=f"{_LETRA_COLUMNA[col]}{fila_nueva}", value_input_option="USER_ENTERED")
                asignados[col] = {"fila": fila_nueva, "maniobra": f["maniobra"], "valor": valor}
                estado["origen_fijo"] = True
                continue
            if fila_base > 1 and estado["origen_fijo"]:
                # La copia de arriba trajo el valor fijo de la fila anterior — se restaura la fórmula.
                if estado["fila_formula"] is not None:
                    sheets.copiar_fila(hoja, fila_origen=estado["fila_formula"], fila_destino=fila_nueva,
                                       num_columnas=col, col_inicio=col - 1)
                else:
                    hoja.update([[""]], range_name=f"{_LETRA_COLUMNA[col]}{fila_nueva}", value_input_option="USER_ENTERED")
            estado["origen_fijo"] = False
        fila_base = fila_nueva

    return {
        "guardadas": guardadas, "hoja_url": hoja.url,
        "carro_canasta": asignados[_COL_CARRO_CANASTA], "descargo": asignados[_COL_DESCARGO],
    }
