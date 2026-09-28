"""Utilidades de normalización de texto compartidas — puertos directos de Codigo.gs.

Viven aparte (no dentro de data_sources ni services) porque tanto el cliente de Metabase
como los servicios de CAPEX/OPEX las necesitan, y así se evita un import circular.
"""

import unicodedata


def normalizar_codigo(s: str | None) -> str:
    """Puerto de normalizeCode (Codigo.gs línea 1699): CO sin espacios, en mayúsculas."""
    if not s:
        return ""
    return "".join(str(s).split()).upper()


def quitar_acentos(s: str | None) -> str:
    """Puerto de stripAccents (Codigo.gs línea 1704)."""
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if not unicodedata.combining(c))


def normText(s) -> str:
    """Puerto de normText (Codigo.gs línea 1708-1710): minúsculas, sin acentos, con un espacio
    de relleno a cada lado — usado para matches por substring de palabra completa.

    `str(s)` primero, no `(s or "").lower()`: un valor NUMÉRICO de una hoja (ej. "tc_relacion"
    en "Normalizaciones_Indirectas" a veces viene como int, no texto — CO0800000725, Dinovi
    2026-09-28) es truthy, así que `s or ""` lo deja intacto y `.lower()` sobre un int revienta
    ("'int' object has no attribute 'lower'"). Mismo patrón de robustez que ya usa
    quitar_acentos()."""
    if s is None:
        return "  "
    return " " + quitar_acentos(str(s).lower()) + " "
