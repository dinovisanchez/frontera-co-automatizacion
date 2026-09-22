"""OPEX — fuzzy-match de maniobras contra ref_tarifario + cálculo de mano de obra.

Puerto directo de las funciones OPEX de Codigo.gs (líneas 4791-5217): normalizarTextoOpex,
opexSimilitud, buscarManiobraMasParecida, contraparteInstalarDesinstalar, esManiobraTcTpMT,
categoriaDesdeGrupoOpex, buscarManiobraFiltrada y construirOpexDesdeEquipos. Se omite
construirPropuestaOpex (la ruta basada en "Consolidado", texto libre) porque esa hoja solo
tiene los CO cargados a mano — la ruta que de verdad generaliza a cualquier CO es la que
deriva las maniobras del propio alcance de equipos ya calculado por CAPEX.
"""

import re
import time

from core.data_sources.sheets_client import SheetsClient
from core.utils import quitar_acentos
from config.settings import SHEET_REF_TARIFARIO

OPEX_OPERADOR_COLUMNAS = ["CELSIA VALLE", "ELECTROHUILA", "ESSA", "AIRE", "ENEL", "EMCALI", "AFINIA", "OTROS_OR"]
OPEX_UMBRAL_SIMILITUD = 0.35
OPEX_VERBO_OPUESTO = {"instalacion": "retiro", "retiro": "instalacion", "montaje": "desmonte", "desmonte": "montaje"}

QUERY_MANIOBRA_POR_CATEGORIA_OPEX = {
    "medidor": "Instalación de medidor",
    "tc": "Instalación de TC",
    "tp": "Instalación de TP",
    "bloque_pruebas": "Instalación de bloque de pruebas",
    "celda": "Montaje de celda",
}

# Palabra(s) que la maniobra candidata DEBE contener antes de aceptarla por similitud — sin
# esto, plantillas genéricas ("Instalación de...") colapsan las 5 categorías en un solo match
# equivocado (caso real CO0100002908, ver Codigo.gs línea 5074-5082).
PALABRAS_CLAVE_POR_CATEGORIA_OPEX = {
    "medidor": ["medidor"],
    "tc": ["corriente"],
    "tp": ["potencial", "tension"],
    "bloque_pruebas": ["bloque"],
    "celda": ["celda"],
}


def normalizar_texto_opex(s: str | None) -> str:
    sin_acentos = quitar_acentos((s or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", sin_acentos)).strip()


def normalizar_operador_tarifario(or_real: str | None) -> str:
    """Contención, no solo igualdad exacta (caso real: "AFINIA CARIBE_MAR" debe matchear "AFINIA")."""
    norm = normalizar_texto_opex(or_real)
    for columna in OPEX_OPERADOR_COLUMNAS:
        col_norm = normalizar_texto_opex(columna)
        if norm == col_norm or col_norm in norm or norm in col_norm:
            return columna
    return "OTROS_OR"


def _tokens(normalizado: str) -> list[str]:
    return [t for t in normalizado.split(" ") if t]


def opex_similitud(a_norm: str, b_norm: str) -> float:
    ta, tb = _tokens(a_norm), _tokens(b_norm)
    if not ta or not tb:
        return 0.0
    set_a = set(ta)
    comunes = len({t for t in tb if t in set_a})
    union = set(ta) | set(tb)
    return comunes / len(union) if union else 0.0


def buscar_maniobra_mas_parecida(texto_libre: str | None, maniobras_reales: list[str], umbral: float = OPEX_UMBRAL_SIMILITUD) -> str | None:
    if not texto_libre:
        return None
    norm = normalizar_texto_opex(texto_libre)
    mejor, mejor_score = None, umbral
    for m in maniobras_reales:
        score = opex_similitud(norm, normalizar_texto_opex(m))
        if score >= mejor_score:
            mejor, mejor_score = m, score
    return mejor


def buscar_maniobra_filtrada(maniobras_reales: list[str], palabras_clave: list[str], texto_query: str, umbral: float = OPEX_UMBRAL_SIMILITUD) -> str | None:
    candidatas = [m for m in maniobras_reales if any(p in normalizar_texto_opex(m) for p in palabras_clave)]
    if not candidatas:
        return None
    return buscar_maniobra_mas_parecida(texto_query, candidatas, umbral)


def contraparte_instalar_desinstalar(maniobra_real: str, maniobras_reales: list[str]) -> str | None:
    norm = normalizar_texto_opex(maniobra_real)
    primera_palabra = norm.split(" ")[0] if norm else ""
    opuesto = OPEX_VERBO_OPUESTO.get(primera_palabra)
    if not opuesto:
        return None
    candidato = opuesto + norm[len(primera_palabra):]
    return buscar_maniobra_mas_parecida(candidato, maniobras_reales)


def es_maniobra_tc_tp_mt(maniobra_real: str) -> bool:
    norm = normalizar_texto_opex(maniobra_real)
    return bool(re.search(r"\b(tcs|tps)\b", norm) and re.search(r"\bmt\b", norm) and re.search(r"(montaje|desmonte)", norm))


def categoria_desde_grupo_opex(grupo: str) -> str | None:
    g = normalizar_texto_opex(grupo)
    if "medidor" in g:
        return "medidor"
    if g == "tc" or "transformador de corriente" in g:
        return "tc"
    if g == "tp" or "transformador de potencia" in g or "transformador de tension" in g:
        return "tp"
    if "bloque" in g:
        return "bloque_pruebas"
    if "celda" in g:
        return "celda"
    if "cable" in g:
        return "cable"
    return None


_CACHE_TARIFARIO: dict = {"expira_en": 0.0, "datos": None}
_CACHE_TTL_SEG = 21600  # 6h, igual que Codigo.gs (línea 4842)


def obtener_ref_tarifario_cacheado(sheets: SheetsClient) -> dict:
    ahora = time.monotonic()
    if _CACHE_TARIFARIO["datos"] is not None and _CACHE_TARIFARIO["expira_en"] > ahora:
        return _CACHE_TARIFARIO["datos"]

    hoja = sheets.hoja_por_nombre(SHEET_REF_TARIFARIO)
    valores = sheets.leer_todo(hoja)
    header = valores[0]
    maniobras: list[str] = []
    precios: dict[str, dict[str, float]] = {}
    for fila in valores[1:]:
        nombre = (fila[0] or "").strip()
        if not nombre:
            continue
        maniobras.append(nombre)
        precios[nombre] = {}
        for c in range(1, len(header)):
            operador = (header[c] or "").strip()
            if not operador:
                continue
            try:
                precios[nombre][operador] = float(fila[c]) if fila[c] not in ("", None) else 0.0
            except ValueError:
                precios[nombre][operador] = 0.0

    resultado = {"maniobras": maniobras, "precios": precios}
    _CACHE_TARIFARIO.update(datos=resultado, expira_en=ahora + _CACHE_TTL_SEG)
    return resultado
