"""Escribe la propuesta ya confirmada por el usuario en la hoja "Equipos" — puerto de
guardarAlcanceProvisional (Codigo.gs). Primero rellena los "huecos" que ya existan para este
CO (filas con cliente/OR/maniobra pero SKU vacío, ej. de un intento anterior); lo que sobre se
inserta justo debajo de la última fila de este CO (o al final de la hoja si no tenía ninguna).

La hoja real tiene 9 columnas, no 7: H/I son fórmulas de costo (VLOOKUP contra ref_capex) que
dependen del SKU de esa misma fila — confirmado por Dinovi, 2026-09-22 (antes de este fix, esas
2 columnas quedaban en blanco porque solo se escribían A:G). Por eso cada fila nueva se inserta
COPIANDO primero la fila de referencia completa (como el copyTo() del original, que arrastra
las fórmulas con sus referencias ajustadas a la fila nueva) y recién después se sobrescribe
A:G con los valores reales — nunca al revés, o se perdería la fórmula.
"""

from core.data_sources.sheets_client import SheetsClient
from core.services.hoja_origen_equipos import leer_equipos_existentes, leer_origen_alcance
from core.utils import normalizar_codigo
from config.settings import SHEET_EQUIPOS

_NUM_COLUMNAS_EQUIPOS = 9  # A:I — A:G son datos, H:I son fórmulas de costo


def guardar_filas_equipos(sheets: SheetsClient, co_raw: str, filas: list[dict], maniobra_respaldo: str | None = None) -> dict:
    """`filas`: [{"sku": str, "cantidad": int, "tipo": str}, ...] — ya filtradas/confirmadas
    por el usuario (sin las que marcó "excluir"). cliente/OR/maniobra se toman de la hoja
    "Data" (leer_origen_alcance), igual que hacía el original: el usuario nunca los escribe
    a mano en esta pantalla.

    `maniobra_respaldo`: muchos CO tienen la columna "Maniobra" vacía en "Data" — confirmado
    por Dinovi, 2026-09-22 (CO0100001596: cliente/OR/SKU sí venían, maniobra no). En vez de
    dejar esa celda en blanco en "Equipos", se usa este texto (típicamente la clasificación,
    ej. "Normalización") cuando la hoja no trae nada.
    """
    co = normalizar_codigo(co_raw)
    if not filas:
        raise ValueError("No hay filas para guardar.")

    origen = leer_origen_alcance(sheets, co)
    maniobra = origen["maniobra"] or maniobra_respaldo or ""
    existentes = leer_equipos_existentes(sheets, co)
    hoja = sheets.hoja_por_nombre(SHEET_EQUIPOS)

    # Huecos: filas que ya existían para este CO con SKU vacío (ej. de un guardado anterior a
    # medias) — se rellenan ANTES de insertar nada nuevo, igual que el original (Dinovi,
    # 2026-09-22: "sobre la que hay dejas un sku [vacío]" — no estaba reutilizando esas filas).
    huecos = sorted(f["fila"] for f in existentes if not f.get("sku"))
    idx_hueco = 0

    # OJO: hoja.row_count es el tamaño del GRID (a menudo con relleno de filas vacías, ej.
    # 1000), no la última fila con contenido real — usarlo como base dejaba un hueco enorme
    # de filas en blanco antes de la fila realmente guardada cuando el CO no tenía filas
    # previas (Dinovi, 2026-09-22). len(col_values(1)) sí refleja la última fila con datos.
    fila_base = max((f["fila"] for f in existentes), default=None) or len(hoja.col_values(1))
    guardadas = []
    for f in filas:
        valores_fila = [co, origen["cliente"], origen["or"], maniobra, f["sku"], f.get("cantidad", 1), f.get("tipo", "")]
        if idx_hueco < len(huecos):
            fila_destino = huecos[idx_hueco]
            idx_hueco += 1
            hoja.update(f"A{fila_destino}:G{fila_destino}", [valores_fila], value_input_option="USER_ENTERED")
        else:
            fila_nueva = fila_base + 1
            hoja.insert_rows([[""] * _NUM_COLUMNAS_EQUIPOS], row=fila_nueva, inherit_from_before=True)
            if fila_base >= 1:
                sheets.copiar_fila(hoja, fila_origen=fila_base, fila_destino=fila_nueva, num_columnas=_NUM_COLUMNAS_EQUIPOS)
            hoja.update(f"A{fila_nueva}:G{fila_nueva}", [valores_fila], value_input_option="USER_ENTERED")
            fila_base = fila_nueva
        guardadas.append(valores_fila)

    return {"guardadas": guardadas, "hoja_url": hoja.url}
