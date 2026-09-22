"""3 hojas externas que ya traen datos de ingeniería calculados a mano, o que cubren un CO
cuando no hay ninguna acta disponible. Puerto de leerFilaPorCoEnHoja/colPorNombre/
buscarEnHojaCambioNT/buscarEnHojaNormalizacionesIndirectas/buscarEnHojaMaestra (Codigo.gs
líneas 2919-3070). Todas confirmadas visualmente contra las hojas reales el 2026-09-22.

buscarEnHojaMaestra corrige un bug real del original: la columna "Propiedad de Activos" casi
nunca dice literalmente "Exclusivo"/"Compartido" — los valores reales son "OR" (activo del
operador de red = compartido) y "Usuario" (activo del cliente = exclusivo). El código
original solo buscaba las palabras "exclusiv"/"compartid" como substring, así que para la
inmensa mayoría de filas esto quedaba en null sin que nadie lo notara.
"""

import re

from core.data_sources.sheets_client import SheetsClient
from core.utils import normalizar_codigo, quitar_acentos
from config.settings import CONTROL_SHEET_ID, MAESTRO_GID, NORMINDIRECTAS_GID, NTCAMBIO_GID, NTCAMBIO_SHEET_ID


def extraer_ratio_de_texto(texto: str | None) -> str | None:
    """Extrae "10/5" o "7.5-15/5" de un texto libre (ya con decimales normalizados)."""
    m = re.search(r"(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)\s*/\s*5", str(texto or ""))
    return f"{m.group(1)}/5" if m else None


def _leer_fila_por_co_en_hoja(sheets: SheetsClient, spreadsheet_id: str, gid: int, co: str) -> dict | None:
    """{"header": [...], "fila": [...]} o None — columna A siempre es el CO, misma convención
    de todo el proyecto."""
    hoja = sheets.hoja_externa_por_gid(spreadsheet_id, gid)
    if not hoja:
        return None
    datos = sheets.leer_todo(hoja, sin_formato=True)
    if len(datos) < 2:
        return None
    # Algunos encabezados reales traen saltos de línea internos (ej. "Factor \nFx",
    # "Fecha \nIngreso\n(mm/dd/aa)") — .strip() solo saca los de los extremos, así que sin
    # colapsar los internos a un espacio, _col_por_nombre nunca encontraba esas columnas
    # (bug real confirmado 2026-09-22 con CO0200001836: "Factor Fx" siempre salía null).
    header = [re.sub(r"\s+", " ", quitar_acentos(str(h or "").lower())).strip() for h in datos[0]]
    for fila in datos[1:]:
        if fila and normalizar_codigo(fila[0]) == co:
            return {"header": header, "fila": fila}
    return None


def _col_por_nombre(header: list[str], nombres_candidatos: str | list[str]) -> int:
    candidatos = nombres_candidatos if isinstance(nombres_candidatos, list) else [nombres_candidatos]
    for candidato in candidatos:
        buscado = quitar_acentos(candidato.lower())
        for i, h in enumerate(header):
            if h == buscado:
                return i
    for candidato in candidatos:
        buscado = quitar_acentos(candidato.lower())
        for i, h in enumerate(header):
            if buscado in h:
                return i
    return -1


def buscar_en_hoja_cambio_nt(sheets: SheetsClient, co: str) -> dict | None:
    """"Data cambio NT" (gid NTCAMBIO_GID): para COs que ya pasaron el análisis de cambio de
    Nivel de Tensión (Art.19) — trae el SKU de TC/TP/Celda/Medidor y metros de cable YA
    calculados a mano por ingeniería."""
    encontrado = _leer_fila_por_co_en_hoja(sheets, NTCAMBIO_SHEET_ID, NTCAMBIO_GID, co)
    if not encontrado:
        return None
    header, fila = encontrado["header"], encontrado["fila"]

    def val(nombre):
        c = _col_por_nombre(header, nombre)
        return fila[c] if c != -1 and c < len(fila) and fila[c] != "" else None

    return {
        "nivel_tension": val("nivel de tension"),
        "punto_medicion": val("punto de medicion"),
        "tipo_medida": val("tipo de medida"),
        "capacidad_kva": val("capacidad kva") if isinstance(val("capacidad kva"), (int, float)) else None,
        "sku_tcs": val("sku tcs"), "costo_tcs": val("costo tcs"),
        "sku_tps": val("sku tps"), "costo_tps": val("costo tps"),
        "tipo_bloque": val("tipo bloque"), "costo_bloque": val("costo bloque"),
        "metros_cable_control": val("metros cable control") if isinstance(val("metros cable control"), (int, float)) else None,
        "costo_cable_control": val("costo cable control"),
        "medidor": val("medidor"), "costo_medidor": val("costo medidor"),
        "celda": val("celda"), "costo_celda": val("costo celda"),
        "maniobra_nt2": val("maniobra nt2"),
    }


def buscar_en_hoja_normalizaciones_indirectas(sheets: SheetsClient, co: str) -> dict | None:
    """"Normalizaciones_Indirectas" (mismo libro, gid NORMINDIRECTAS_GID): relación de TC/TP ya
    calculada, cada una con su columna "Cantidad" AL LADO (desplazamiento de columna, no
    búsqueda por nombre — "cantidad" se repite varias veces en esta hoja)."""
    encontrado = _leer_fila_por_co_en_hoja(sheets, NTCAMBIO_SHEET_ID, NORMINDIRECTAS_GID, co)
    if not encontrado:
        return None
    header, fila = encontrado["header"], encontrado["fila"]

    def idx(nombre):
        return _col_por_nombre(header, nombre)

    def en(i):
        return fila[i] if i != -1 and i < len(fila) and fila[i] != "" else None

    def despues(i, n):
        return en(i + n) if i != -1 else None

    i_tc, i_tp = idx(["tc relacion", "tc realacion"]), idx("tp relacion")
    i_bornera, i_medidor, i_cable, i_celda = idx("bornera"), idx("medidor"), idx("cable"), idx("celda")

    return {
        "capacidad_transformador": en(idx("capacidad del transformador")),
        "propiedad_activos": en(idx("propiedad de activos")),
        "nivel_tension": en(idx("nivel de tension")),
        "tipo": en(idx("tipo")),
        "tc_relacion": en(i_tc), "tc_cantidad": despues(i_tc, 1), "costo_tcs": despues(i_tc, 2),
        "tp_relacion": en(i_tp), "tp_cantidad": despues(i_tp, 1), "costo_tps": despues(i_tp, 2),
        "bornera": en(i_bornera), "bornera_cantidad": despues(i_bornera, 1), "costo_bornera": despues(i_bornera, 2),
        "medidor": en(i_medidor), "medidor_cantidad": despues(i_medidor, 1), "costo_medidor": despues(i_medidor, 2),
        "cable": en(i_cable), "cable_cantidad": despues(i_cable, 1), "costo_cable": despues(i_cable, 2),
        "celda": en(i_celda), "costo_celda": despues(i_celda, 1),
    }


def _propiedad_activos_a_uso(texto: str | None) -> str | None:
    """Corrige el bug del original: "OR" (activo del operador de red) = compartido, "Usuario"
    (activo del cliente) = exclusivo. También reconoce "exclusiv"/"compartid" literales por si
    algún día se escriben así."""
    t = quitar_acentos((texto or "").lower().strip())
    if not t:
        return None
    if "exclusiv" in t or t == "usuario":
        return "exclusivo"
    if "compartid" in t or t == "or":
        return "compartido"
    return None


def buscar_en_hoja_maestra(sheets: SheetsClient, co: str) -> dict | None:
    """Hoja "BD_Telemedida" (columna A "ID Interno" = CO) — a diferencia de las dos anteriores
    (solo casos puntuales), tiene una fila por CADA CO: es la única que sirve cuando no hay
    ninguna acta disponible."""
    encontrado = _leer_fila_por_co_en_hoja(sheets, CONTROL_SHEET_ID, MAESTRO_GID, co)
    if not encontrado:
        return None
    header, fila = encontrado["header"], encontrado["fila"]

    def idx(nombre):
        return _col_por_nombre(header, nombre)

    def en(i):
        return fila[i] if i != -1 and i < len(fila) and fila[i] != "" else None

    medida_texto = quitar_acentos(str(en(idx("medida")) or "").lower().strip())
    medida = medida_texto if medida_texto in ("directa", "semidirecta", "indirecta") else None

    conexion_texto = quitar_acentos(str(en(idx("conexion")) or "").lower().strip())
    elementos = 3 if "trifasic" in conexion_texto else (2 if "bifasic" in conexion_texto else None)
    fases = 3 if "trifasic" in conexion_texto else (2 if "bifasic" in conexion_texto else (1 if "monofasic" in conexion_texto else None))

    capacidad_raw = en(idx("capacidad transformador"))
    factor_fx = en(idx("factor fx"))

    return {
        "medida": medida,
        "conexion": conexion_texto or None,
        "elementos": elementos,
        "fases": fases,
        "nivel_tension": en(idx("nivel de tension")),
        "propiedad_activos": _propiedad_activos_a_uso(en(idx("propiedad de activos"))),
        "capacidad_transformador": float(capacidad_raw) if isinstance(capacidad_raw, (int, float)) else None,
        "or": en(idx("or")),
        "tipo_mercado": en(idx("tipo mercado")),
        "marca_medidor": en(idx("marca medidor activo")),
        "modelo_medidor": en(idx("modelo medidor")),
        "factor_fx": float(factor_fx) if isinstance(factor_fx, (int, float)) else None,
    }
