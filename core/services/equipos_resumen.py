"""Lee TODA la hoja "Equipos" de una sola vez y la agrupa por CO — para la pestaña "OPEX desde
Equipos" (Dinovi, 2026-09-29): backfill de mano de obra para CO's cuyo alcance de equipos ya se
guardó (por este sistema o antes) pero cuyo OPEX nunca se calculó o quedó incompleto.

Por qué esto no reusa leer_equipos_existentes() (hoja_origen_equipos.py) tal cual: esa función
SÍ lee la hoja entera pero filtra a un solo CO puntual — para listar TODOS los CO agrupados de
una sola pasada hace falta la misma lectura sin ese filtro (mismo costo de red: una sola llamada
a Sheets, igual que hoy hace leer_equipos_existentes() por cada CO individual).

construir_opex_desde_equipos() (opex_desde_equipos.py) necesita tipo_medida_final/ubicacion/
es_instalacion_nueva/tipo_medida_actual — NINGUNO de estos se guarda en "Equipos" (solo sku/
cantidad/tipo/maniobra). tipo_medida_final y ubicacion SÍ se pueden inferir del texto libre del
SKU del Medidor/TC/TP ya guardado, reutilizando los mismos regex de catalogo_capex.py que ya usa
CAPEX para lo mismo. es_instalacion_nueva y tipo_medida_actual no tienen ninguna señal
persistida — se piden en la tarjeta del frontend, esto solo entrega lo que SÍ se puede inferir.
"""

import re
from dataclasses import dataclass, field

from core.data_sources.sheets_client import SheetsClient, con_reintento_sheets
from core.services.catalogo_capex import parsear_medidor, parsear_tc, parsear_tp
from core.utils import normalizar_codigo
from config.settings import FILA_INICIO_HOJA_ORIGEN, SHEET_EQUIPOS, SHEET_OPEX

# Confirmado en producción (Dinovi, 2026-09-29): además del bloque de encabezado del inicio
# (ver FILA_INICIO_HOJA_ORIGEN), "Equipos" tiene al menos una fila de encabezado repetida más
# abajo en la hoja (columna A literal "CO", columna E literal "Maniobra") — probablemente
# pegada a mano como separador visual en algún momento. leer_equipos_existentes() nunca la nota
# porque busca un CO puntual (nunca es igual a "CO"), pero acá SÍ colaba como un CO fantasma.
# Validar el formato en vez de solo "no vacío" filtra esto sin importar dónde aparezca.
_PATRON_CO_VALIDO = re.compile(r"^CO\d+$")

# Mismas categorías/palabras clave que ETIQUETAS_EQUIPO_ALCANCE en el frontend (index.html) —
# el valor real guardado en la columna "Tipo" de Equipos es la forma larga ("Transformador de
# corriente", no "TC"), así que se matchea por substring sobre esa forma larga.
_PALABRAS_CATEGORIA = {
    "medidor": "medidor",
    "tc": "corriente",
    "tp": "potencial",
    "bloque_pruebas": "bloque",
    "celda": "celda",
    "cable": "cable",
}


def _categoria_de_tipo(tipo: str | None) -> str | None:
    t = (tipo or "").lower()
    for categoria, palabra in _PALABRAS_CATEGORIA.items():
        if palabra in t:
            return categoria
    return None


@dataclass
class CoEnEquipos:
    co: str
    cliente: str
    or_: str
    maniobra: str
    filas: list[dict] = field(default_factory=list)
    tipo_medida_final_inferido: str | None = None
    ubicacion_inferida: str | None = None
    secciones: dict = field(default_factory=dict)
    celda_sku: str | None = None
    filas_cable: list[dict] = field(default_factory=list)
    filas_opex_existentes: int = 0


def _inferir_tipo_medida(filas: list[dict]) -> str | None:
    for f in filas:
        if _categoria_de_tipo(f.get("tipo")) != "medidor" or not f.get("sku"):
            continue
        tipos = parsear_medidor(f["sku"])["tipos_medida"]
        if len(tipos) == 1:
            return tipos[0]
    return None


def _inferir_ubicacion(filas: list[dict]) -> str | None:
    for f in filas:
        categoria = _categoria_de_tipo(f.get("tipo"))
        if categoria not in ("tc", "tp") or not f.get("sku"):
            continue
        parsear = parsear_tc if categoria == "tc" else parsear_tp
        ubicacion = parsear(f["sku"]).get("ubicacion")
        if ubicacion:
            return ubicacion
    return None


def _contar_opex_por_co(sheets: SheetsClient) -> dict[str, int]:
    try:
        hoja = sheets.hoja_por_nombre(SHEET_OPEX)
    except RuntimeError:
        return {}
    columna_co = con_reintento_sheets(hoja.col_values, 1)
    conteo: dict[str, int] = {}
    for valor in columna_co[1:]:
        co = normalizar_codigo(valor)
        if _PATRON_CO_VALIDO.match(co):
            conteo[co] = conteo.get(co, 0) + 1
    return conteo


def listar_cos_en_equipos(sheets: SheetsClient) -> list[CoEnEquipos]:
    hoja = sheets.hoja_por_nombre(SHEET_EQUIPOS)
    ultima_fila = hoja.row_count
    conteo_opex = _contar_opex_por_co(sheets)
    if ultima_fila < FILA_INICIO_HOJA_ORIGEN:
        return []

    # "Equipos" y "Data" son el mismo tab físico (ver hoja_origen_equipos.py) — el bloque de
    # encabezado real ocupa varias filas (título + nombres de columna), no solo la fila 1, por
    # eso leer_origen_alcance() ya arranca en FILA_INICIO_HOJA_ORIGEN (4) en vez de 1. Sin este
    # ajuste, una fila de encabezado ("CO"/"Maniobra" literal) se cuela como un CO fantasma.
    datos = sheets.leer_rango(hoja, FILA_INICIO_HOJA_ORIGEN, 1, ultima_fila - FILA_INICIO_HOJA_ORIGEN + 1, 8)
    por_co: dict[str, CoEnEquipos] = {}
    orden: list[str] = []
    for f in datos:
        co = normalizar_codigo(f[0] if len(f) > 0 else "")
        if not _PATRON_CO_VALIDO.match(co):
            continue
        if co not in por_co:
            por_co[co] = CoEnEquipos(
                co=co,
                cliente=f[1] if len(f) > 1 else "",
                or_=f[2] if len(f) > 2 else "",
                maniobra=f[4] if len(f) > 4 else "",
                filas_opex_existentes=conteo_opex.get(co, 0),
            )
            orden.append(co)
        sku = f[5] if len(f) > 5 else ""
        cantidad = f[6] if len(f) > 6 else ""
        tipo = f[7] if len(f) > 7 else ""
        if sku or tipo:
            por_co[co].filas.append({"sku": sku, "cantidad": cantidad, "tipo": tipo})

    for co in orden:
        registro = por_co[co]
        registro.tipo_medida_final_inferido = _inferir_tipo_medida(registro.filas)
        registro.ubicacion_inferida = _inferir_ubicacion(registro.filas)
        secciones = {}
        for f in registro.filas:
            categoria = _categoria_de_tipo(f.get("tipo"))
            if categoria and categoria != "cable":
                secciones[categoria] = True
        registro.secciones = secciones
        celda = next((f for f in registro.filas if _categoria_de_tipo(f.get("tipo")) == "celda"), None)
        registro.celda_sku = celda["sku"] if celda else None
        registro.filas_cable = [
            {"grupo": f.get("tipo"), "cantidad": f.get("cantidad") or 1}
            for f in registro.filas if _categoria_de_tipo(f.get("tipo")) == "cable"
        ]

    return [por_co[co] for co in orden]
