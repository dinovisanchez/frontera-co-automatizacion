"""Compara el alcance que el motor calculó (propuesta CAPEX) contra lo que "Data cambio NT"/
"Normalizaciones_Indirectas" ya tienen anotado para el mismo CO — para la comparación masiva
de ~400 CO (Dinovi, 2026-09-24).

Primer corte razonable, aislado a propósito: es muy probable que el criterio exacto de
"coincide" necesite afinarse con los primeros resultados reales del lote, igual que casi toda
regla de este proyecto — así se puede tocar solo este módulo sin rehacer el resto.
"""

from core.services.catalogo_capex import normalizar_decimales, parse_ratio_range
from core.services.hojas_ingenieria import extraer_ratio_de_texto
from core.utils import normText

CATEGORIAS_COMPARABLES = ["tc", "tp", "medidor", "celda"]


def _texto_hoja_por_categoria(datos_hoja: dict, fuente: str, categoria: str) -> str | None:
    if fuente == "cambio_nt":
        mapa = {"tc": "sku_tcs", "tp": "sku_tps", "medidor": "medidor", "celda": "celda"}
    else:  # norm_indirectas
        mapa = {"tc": "tc_relacion", "tp": "tp_relacion", "medidor": "medidor", "celda": "celda"}
    return datos_hoja.get(mapa[categoria])


def _grupo_a_categoria(grupo: str | None) -> str | None:
    g = (grupo or "").strip().lower()
    return g if g in ("tc", "tp", "medidor", "celda") else None


def _sku_nuestro_por_categoria(propuesta: list[dict], categoria: str) -> str | None:
    for p in propuesta:
        if _grupo_a_categoria(p.get("grupo")) == categoria:
            return p.get("sku")
    return None


def _ratio_de(texto: str | None) -> dict | None:
    ratio = extraer_ratio_de_texto(normalizar_decimales(texto)) if texto else None
    return parse_ratio_range(ratio) if ratio else None


def _coincide_texto_libre(nuestro: str, hoja: str) -> bool:
    """Solapamiento de palabras (≥50% de la más corta) — mismo criterio de fondo que
    catalogo_capex.normalizar_sku_contra_catalogo (0.6, aquí un poco más laxo porque acá
    comparamos dos textos libres, no un texto libre contra un SKU exacto de catálogo)."""
    palabras_n = [w for w in normText(nuestro).strip().split() if len(w) > 2]
    palabras_h = [w for w in normText(hoja).strip().split() if len(w) > 2]
    if not palabras_n or not palabras_h:
        return False
    comunes = sum(1 for w in palabras_n if w in palabras_h)
    return comunes >= max(1, int(min(len(palabras_n), len(palabras_h)) * 0.5))


def _coincide(categoria: str, nuestro: str | None, hoja: str) -> bool:
    if not nuestro:
        return False
    if categoria in ("tc", "tp"):
        rango_n, rango_h = _ratio_de(nuestro), _ratio_de(hoja)
        if rango_n and rango_h:
            return rango_n["min"] == rango_h["min"] and rango_n["max"] == rango_h["max"]
        return _coincide_texto_libre(nuestro, hoja)
    return _coincide_texto_libre(nuestro, hoja)


def comparar_propuesta_vs_hoja(propuesta: list[dict], datos_hoja: dict, fuente: str) -> dict:
    """`fuente`: "cambio_nt" | "norm_indirectas" — de qué hoja viene `datos_hoja`, porque cada
    una nombra sus columnas distinto (ver _texto_hoja_por_categoria).

    Una categoría que la hoja no menciona no cuenta ni a favor ni en contra de
    `coincide_total` — si la hoja no dice nada de Medidor, por ejemplo, no hay nada que
    comparar ahí.
    """
    campos = {}
    for categoria in CATEGORIAS_COMPARABLES:
        texto_hoja = _texto_hoja_por_categoria(datos_hoja, fuente, categoria)
        if not texto_hoja:
            continue
        texto_nuestro = _sku_nuestro_por_categoria(propuesta, categoria)
        campos[categoria] = {
            "nuestro": texto_nuestro,
            "hoja": texto_hoja,
            "coincide": _coincide(categoria, texto_nuestro, texto_hoja),
        }
    coincide_total = bool(campos) and all(c["coincide"] for c in campos.values())
    return {"campos": campos, "coincide_total": coincide_total}
