"""Catálogo `ref_capex` — puerto de obtenerCatalogoRefCapex/parsearTC/parsearTP/parsearMedidor/
normalizarSkuContraCatalogo/normalizarMedidorContraCatalogo (Codigo.gs líneas 3782-3884,
3151-3165, 378-385). Sin columnas técnicas propias: todo (ratio/ubicación/burden/clase de
tensión) se extrae por regex del texto libre en la columna A (SKU/Item CAPEX).
"""

import re

from core.data_sources.sheets_client import SheetsClient
from core.utils import normText, quitar_acentos
from config.settings import SHEET_REF_CAPEX


def normalizar_decimales(texto: str | None) -> str:
    """Sheets en configuración CO a veces da números con coma decimal ("7,5/5") — solo
    convierte la coma DECIMAL (entre dígitos), nunca una coma de separador de lista."""
    return re.sub(r"(\d),(\d)", r"\1.\2", str(texto or ""))


def parse_ratio_range(ratio: str | None) -> dict | None:
    if not ratio:
        return None
    primario = ratio.split("/")[0]
    if "-" in primario:
        a, b = primario.split("-")
        return {"min": float(a), "max": float(b)}
    v = float(primario)
    return {"min": v, "max": v}


def parsear_tc(sku: str) -> dict:
    ratio_m = re.search(r"(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)\s*/\s*5", sku)
    ratio = f"{ratio_m.group(1)}/5" if ratio_m else None
    ubicacion = "interior" if re.search(r"interior", sku, re.I) else ("exterior" if re.search(r"exterior", sku, re.I) else None)
    burden_m = re.search(r"[Bb](?:urden)?\.?\s*(\d+(?:\.\d+)?)\s*VA", sku) or re.search(r"(\d+(?:\.\d+)?)\s*VA", sku)
    burden = float(burden_m.group(1)) if burden_m else None
    kv_m = re.search(r"[Tt]\.?\s*(\d+(?:\.\d+)?)\s*k[Vv]", sku) or re.search(r"-\s*[Tt]\s*(\d+(?:\.\d+)?)\s*$", sku)
    kv = float(kv_m.group(1)) if kv_m else None
    con_cable = True if re.search(r"con\s+cable", sku, re.I) else (False if re.search(r"sin\s+cable", sku, re.I) else None)
    montaje = "barra_pasante" if re.search(r"barra\s+pasante", sku, re.I) else ("ventana" if re.search(r"ventana", sku, re.I) else None)
    return {"ratio": ratio, "ratio_range": parse_ratio_range(ratio), "ubicacion": ubicacion, "burden": burden, "kv": kv, "con_cable": con_cable, "montaje": montaje}


def parsear_tp(sku: str) -> dict:
    after_tp = re.sub(r"^TP\s+", "", sku, flags=re.I)
    v_idx_m = re.search(r"\sV\b", after_tp)
    ratio_txt = (after_tp[: v_idx_m.start()] if v_idx_m else after_tp).replace(" ", "")
    partes = ratio_txt.split("/")
    primario = float(re.sub(r"[^\d.]", "", partes[0])) if partes and partes[0] and re.sub(r"[^\d.]", "", partes[0]) else None
    con_raiz_primario = "√" in (partes[0] if partes else "")
    secundario = float(re.sub(r"[^\d.]", "", partes[1])) if len(partes) > 1 and partes[1] and re.sub(r"[^\d.]", "", partes[1]) else None
    con_raiz_secundario = "√" in (partes[1] if len(partes) > 1 else "")
    ubicacion = "interior" if re.search(r"interior", sku, re.I) else ("exterior" if re.search(r"exterior", sku, re.I) else None)
    burden_m = re.search(r"(\d+(?:\.\d+)?)\s*VA", sku)
    burden = float(burden_m.group(1)) if burden_m else None
    kv_m = re.search(r"(\d+(?:\.\d+)?)\s*k[Vv]", sku)
    kv = float(kv_m.group(1)) if kv_m else None
    return {"primario": primario, "con_raiz_primario": con_raiz_primario, "secundario": secundario, "con_raiz_secundario": con_raiz_secundario, "ubicacion": ubicacion, "burden": burden, "kv": kv}


def parsear_medidor(sku: str) -> dict:
    """directa/semidirecta/indirecta + número de fases desde el nombre/modelo del medidor."""
    t = sku or ""
    sin_tildes = quitar_acentos(t).lower()
    es_indirecta = bool(re.search(r"indirecta", sin_tildes))
    es_semidirecta = bool(re.search(r"semidirecta", sin_tildes))
    sin_tipos_compuestos = re.sub(r"semidirecta", "", re.sub(r"indirecta", "", sin_tildes))
    es_directa = bool(re.search(r"directa", sin_tipos_compuestos))
    tipos_medida = [t2 for t2, cond in (("indirecta", es_indirecta), ("semidirecta", es_semidirecta), ("directa", es_directa)) if cond]

    fases = 3 if re.search(r"trifasic", sin_tildes) else (2 if re.search(r"bifasic", sin_tildes) else (1 if re.search(r"monofasic", sin_tildes) else None))
    if fases is None:
        fase_m = re.search(r"\b([123])\s*[x×X]\s*\d+", t)
        if fase_m:
            fases = int(fase_m.group(1))
    if re.search(r"\bP2000D\b", t, re.I):
        if not tipos_medida:
            tipos_medida.append("directa")
        fases = fases if fases is not None else 3
    elif re.search(r"\bC2000\b", t, re.I):
        if not tipos_medida:
            tipos_medida.append("directa")
        fases = fases if fases is not None else 1
    elif re.search(r"\bD2000\b", t, re.I):
        if not tipos_medida:
            tipos_medida.append("directa")
        fases = fases if fases is not None else 2
    return {"tipos_medida": tipos_medida, "fases": fases}


def obtener_catalogo_ref_capex(sheets: SheetsClient) -> list[dict]:
    hoja = sheets.hoja_por_nombre(SHEET_REF_CAPEX)
    valores = sheets.leer_todo(hoja, sin_formato=True)
    catalogo = []
    for fila in valores[1:]:
        sku = str(fila[0] or "").strip()
        if not sku:
            continue
        categoria = str(fila[1] or "").strip()
        costo = fila[2] if len(fila) > 2 else None
        item = {"sku": sku, "categoria": categoria, "costo": float(costo) if isinstance(costo, (int, float)) else None}
        if categoria == "Transformador de corriente":
            item["tc"] = parsear_tc(sku)
        elif categoria == "Transformador de potencial":
            item["tp"] = parsear_tp(sku)
        catalogo.append(item)
    return catalogo


def normalizar_sku_contra_catalogo(catalogo: list[dict], texto_libre: str | None) -> dict | None:
    """Ítem del catálogo cuyo texto se acerca más a `texto_libre` (de otra fuente, ej. "Data
    cambio NT") — para no escribir un texto que el VLOOKUP contra ref_capex no vaya a encontrar.
    """
    if not texto_libre:
        return None
    texto_norm = normalizar_decimales(texto_libre)
    for item in catalogo:
        if item["sku"].lower() == texto_norm.lower().strip():
            return item
    norm = normText(texto_norm)
    palabras = [w for w in norm.strip().split() if len(w) > 1]
    mejor, mejor_score = None, 0
    for item in catalogo:
        item_norm = normText(item["sku"])
        score = sum(1 for w in palabras if w in item_norm)
        if score > mejor_score:
            mejor, mejor_score = item, score
    return mejor if (mejor and mejor_score >= max(1, int(len(palabras) * 0.6))) else None


def normalizar_medidor_contra_catalogo(catalogo: list[dict], texto_libre: str | None, tipo_medida: str) -> dict | None:
    candidatos_medidor = [i for i in catalogo if i["categoria"] == "Medidor"]
    compatibles = [i for i in candidatos_medidor if not parsear_medidor(i["sku"])["tipos_medida"] or tipo_medida in parsear_medidor(i["sku"])["tipos_medida"]]
    return normalizar_sku_contra_catalogo(compatibles or candidatos_medidor, texto_libre)


def candidatos_por_categoria_alcance(catalogo: list[dict], categoria: str) -> list[dict]:
    mapa = {"medidor": "Medidor", "bloque_pruebas": "Bloque de prueba", "cable": "Cables"}
    if categoria == "celda":
        return [i for i in catalogo if "Celda" in i["categoria"]]
    if categoria == "tc":
        return [i for i in catalogo if i["categoria"] == "Transformador de corriente"][:5]
    if categoria == "tp":
        return [i for i in catalogo if i["categoria"] == "Transformador de potencial"][:5]
    nombre = mapa.get(categoria)
    return [i for i in catalogo if i["categoria"] == nombre] if nombre else []
