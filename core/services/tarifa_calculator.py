"""OPEX — utilidades sobre ref_tarifario: normalización de texto, matching de maniobras y
carga cacheada de la hoja.

Puerto de las funciones OPEX de Codigo.gs (normalizarTextoOpex, opexSimilitud,
buscarManiobraMasParecida, categoriaDesdeGrupoOpex, obtenerRefTarifarioCacheado) MÁS un
matcher nuevo (`buscar_maniobra_por_palabras`) que no existía en el original.

Por qué el matcher nuevo: se verificó la hoja real (Dinovi, 2026-09-21, gid 192919919) y las
72 maniobras NO son plantillas genéricas como "Instalación de TC" — están armadas por tipo de
medida × ubicación (ej. "Instalación semidirecta interior (medidor + bloque + módem + toma
110V si aplica)", "Montaje TCs MT (1–3) – exterior"). El fuzzy-match genérico que traía el
original (buscarManiobraMasParecida contra una plantilla corta) es ambiguo entre variantes muy
parecidas (interior/exterior, con/sin bloque) — `buscar_maniobra_por_palabras` en cambio exige
un conjunto de palabras EXACTO (todas presentes, ninguna de las excluidas) y solo devuelve algo
si el resultado es inequívoco (exactamente una maniobra califica); ver opex_desde_equipos.py
para las 24 combinaciones verificadas contra la hoja real.
"""

import re
import time

from core.data_sources.sheets_client import SheetsClient
from core.utils import quitar_acentos
from config.settings import SHEET_REF_TARIFARIO

OPEX_OPERADOR_COLUMNAS = ["CELSIA VALLE", "ELECTROHUILA", "ESSA", "AIRE", "ENEL", "EMCALI", "AFINIA", "OTROS_OR"]
OPEX_UMBRAL_SIMILITUD = 0.35


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
    """Fuzzy-match genérico — se deja SOLO para "cable" (grupo de la propia fila, ej. "Cable
    señal", ya es un texto específico) y como red de seguridad; para medidor/TC/TP/bloque se
    usa buscar_maniobra_por_palabras, mucho más preciso contra esta hoja."""
    if not texto_libre:
        return None
    norm = normalizar_texto_opex(texto_libre)
    mejor, mejor_score = None, umbral
    for m in maniobras_reales:
        score = opex_similitud(norm, normalizar_texto_opex(m))
        if score >= mejor_score:
            mejor, mejor_score = m, score
    return mejor


def buscar_maniobra_por_palabras(maniobras_reales: list[str], requeridas: list[str], excluidas: list[str] | None = None) -> str | None:
    """Devuelve la maniobra si EXACTAMENTE UNA contiene todas las `requeridas` y ninguna de las
    `excluidas` — None si no hay match o si hay más de uno (ambiguo: la hoja pudo haber
    cambiado, mejor avisar que adivinar).
    """
    excluidas = excluidas or []
    candidatas = []
    for m in maniobras_reales:
        norm = normalizar_texto_opex(m)
        if all(p in norm for p in requeridas) and not any(p in norm for p in excluidas):
            candidatas.append(m)
    return candidatas[0] if len(candidatas) == 1 else None


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
    # sin_formato=True: las celdas de precio se VEN como "$118,750.00" pero necesitamos el
    # número crudo (118750.0) — confirmado al revisar la hoja real (Dinovi, 2026-09-21).
    valores = sheets.leer_todo(hoja, sin_formato=True)
    header = valores[0]
    maniobras: list[str] = []
    precios: dict[str, dict[str, float]] = {}
    for fila in valores[1:]:
        nombre = str(fila[0] or "").strip()
        if not nombre:
            continue
        maniobras.append(nombre)
        precios[nombre] = {}
        for c in range(1, len(header)):
            operador = str(header[c] or "").strip()
            if not operador:
                continue
            valor = fila[c] if c < len(fila) else ""
            precios[nombre][operador] = float(valor) if isinstance(valor, (int, float)) else 0.0

    resultado = {"maniobras": maniobras, "precios": precios}
    _CACHE_TARIFARIO.update(datos=resultado, expira_en=ahora + _CACHE_TTL_SEG)
    return resultado
