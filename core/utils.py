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
