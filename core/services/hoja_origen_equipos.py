"""Hoja "Data" (origen: cliente/OR/maniobra por CO) y hoja "Equipos" (lo ya guardado ahí para
este CO). Puerto de leerFilasOrigenAlcance/leerFilasEquiposExistentes (Codigo.gs líneas
2879-2909).

CONFIRMADO (Dinovi, 2026-09-28): "Data" (por GID_HOJA_ORIGEN) y "Equipos" (por nombre) son el
MISMO tab físico — mismo encabezado exacto, misma fila de ejemplo. leer_origen_alcance() busca
entre TODAS las filas ya guardadas de un CO para reusar su cliente/or/maniobra al agregar
filas nuevas; leer_equipos_existentes() hace lo mismo para encontrar huecos/dónde insertar. Por
eso ambas necesitan el MISMO ajuste de columnas por la columna D nueva ("Propiedad De
Activos") — se corrigió leer_equipos_existentes() el 2026-09-28 pero esta función quedó con el
mapeo viejo de 7 columnas, así que origen["maniobra"] leía la columna D (Propiedad De Activos,
ej. "Usuario") en vez de la E real (Maniobra, "Cambio NT"/"Normalización") — ese valor
equivocado se escribía después en la hoja "Equipos" vía guardar_equipos.py.
"""

from core.data_sources.sheets_client import SheetsClient
from core.utils import normalizar_codigo
from config.settings import FILA_INICIO_HOJA_ORIGEN, GID_HOJA_ORIGEN, SHEET_EQUIPOS


def leer_origen_alcance(sheets: SheetsClient, co: str) -> dict:
    """{"cliente", "or", "maniobra", "filas"} — la primera fila de este CO en la hoja "Data"
    manda para cliente/or/maniobra; "filas" trae TODAS sus filas (co/cliente/or/maniobra/sku/
    cantidad/tipo) para poder ubicar dónde insertar la propuesta nueva.

    Columna D ("Propiedad De Activos") se salta al leer, igual que en leer_equipos_existentes
    (ver docstring del módulo) — por eso se leen 8 columnas (A:H) en vez de 7."""
    hoja = sheets.hoja_por_gid(GID_HOJA_ORIGEN)
    ultima_fila = hoja.row_count
    if ultima_fila < FILA_INICIO_HOJA_ORIGEN:
        return {"cliente": "", "or": "", "maniobra": "", "filas": []}
    datos = sheets.leer_rango(hoja, FILA_INICIO_HOJA_ORIGEN, 1, ultima_fila - FILA_INICIO_HOJA_ORIGEN + 1, 8)
    filas = [
        {"cliente": f[1], "or": f[2], "maniobra": f[4], "sku": f[5], "cantidad": f[6], "tipo": f[7]}
        for f in datos if normalizar_codigo(f[0]) == co
    ]
    return {
        "cliente": filas[0]["cliente"] if filas else "",
        "or": filas[0]["or"] if filas else "",
        "maniobra": filas[0]["maniobra"] if filas else "",
        "filas": filas,
    }


def leer_equipos_existentes(sheets: SheetsClient, co: str) -> list[dict]:
    """Filas YA guardadas para este CO en la hoja "Equipos" — cada una con su número de fila
    real (1-indexado) para poder ubicar dónde insertar filas nuevas.

    Columna D ("Propiedad De Activos", agregada por Dinovi 2026-09-28 — fórmula XLOOKUP ajena
    a este flujo) se salta al leer, igual que al escribir (ver guardar_equipos.py): por eso se
    leen 8 columnas (A:H) en vez de 7 y el índice 4 (antes 3) es "maniobra"."""
    hoja = sheets.hoja_por_nombre(SHEET_EQUIPOS)
    ultima_fila = hoja.row_count
    if ultima_fila < 1:
        return []
    datos = sheets.leer_rango(hoja, 1, 1, ultima_fila, 8)
    return [
        {"fila": i + 1, "cliente": f[1], "or": f[2], "maniobra": f[4], "sku": f[5], "cantidad": f[6], "tipo": f[7]}
        for i, f in enumerate(datos) if normalizar_codigo(f[0]) == co
    ]
