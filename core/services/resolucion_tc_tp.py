"""Búsqueda de candidatos de TC/TP/medidor/celda en el catálogo + reglas específicas por
operador de red. Puerto de buscarCandidatosTC/buscarCandidatosTP/buscarCandidatosMedidor/
ordenarCandidatosCelda/resolverTCDesdeHojas/resolverTPDesdeHojas/esOREPM/
preferirConCablePorOR/inferirUbicacionPorOR (Codigo.gs líneas 272-350, 3977-4038, 3080-3136).
"""

from core.services.catalogo_capex import normalizar_decimales, normalizar_sku_contra_catalogo, parse_ratio_range, parsear_medidor, parsear_tc, parsear_tp
from core.services.hojas_ingenieria import extraer_ratio_de_texto
from core.utils import normText, quitar_acentos


def _compacto(s: str | None) -> str:
    return "".join(c for c in quitar_acentos((s or "").lower()) if c.isalnum())


def preferir_con_cable_por_or(or_real: str | None) -> bool:
    """EMCALI (Cali) pide la variante "con cable" — no descarta las demás, solo las prioriza."""
    return "emcali" in _compacto(or_real)


def es_or_epm(or_real: str | None) -> bool:
    """EPM exige mantener el mismo TC ya instalado en compartido, no recalcularlo."""
    return "epm" in _compacto(or_real)


def inferir_ubicacion_por_or(or_real: str | None, texto_adicional: str | None) -> str | None:
    """La mayoría de fronteras de "Air-e" son exterior, salvo que estén en un centro comercial."""
    compacto = _compacto(or_real)
    if "aire" not in compacto:
        return None
    texto = quitar_acentos((texto_adicional or "").lower())
    return "interior" if "centro comercial" in texto else "exterior"


def buscar_candidatos_tc(
    catalogo: list[dict], relacion_requerida: str | None, ubicacion_requerida: str | None,
    kv_requerido: float | None, burden_requerido: float | None = None, montaje_requerido: str | None = None,
    preferir_con_cable: bool = False,
) -> list[dict]:
    """Hasta 3 candidatos ordenados por puntaje. Burden fijo en 5VA por defecto."""
    burden_requerido = 5.0 if burden_requerido is None else burden_requerido
    necesitado = parse_ratio_range(relacion_requerida)
    items = [i for i in catalogo if i["categoria"] == "Transformador de corriente"]

    def puntaje(item: dict) -> float:
        tc = item["tc"]
        if tc["burden"] != burden_requerido:
            return -1
        # Clase de tensión: DESCALIFICA, no solo penaliza — un TC de 0.72kV (BT) no se puede usar
        # en un circuito de 17.5kV (MT) ni viceversa, no es una cuestión de "mejor ajuste" como la
        # ubicación o el montaje. Antes esto era una penalización (-6) que un acierto de relación
        # (+5) podía superar, dejando pasar un TC de BT como "el mejor candidato" para un CO MT
        # (Dinovi, 2026-09-23, CO0100001344: interior + cambio de NT a Indirecta sugirió "TC 400/5
        # ... T 0.72 kV" solo porque esa relación sí existía en el catálogo de BT).
        if kv_requerido is not None and tc["kv"] is not None and abs(tc["kv"] - kv_requerido) >= 0.01:
            return -1
        p = 3
        if ubicacion_requerida and tc["ubicacion"]:
            p += 2 if tc["ubicacion"] == ubicacion_requerida else -2
        if not preferir_con_cable and montaje_requerido and tc["montaje"]:
            p += 2 if tc["montaje"] == montaje_requerido else -2
        if tc["ratio_range"] and necesitado:
            if tc["ratio_range"]["min"] == necesitado["min"] and tc["ratio_range"]["max"] == necesitado["max"]:
                p += 5
            elif tc["ratio_range"]["min"] <= necesitado["min"] <= tc["ratio_range"]["max"]:
                p += 3
            else:
                p -= 5
        else:
            p -= 5
        return p

    puntuados = [(i, puntaje(i)) for i in items]
    puntuados = [(i, s) for i, s in puntuados if s > 0]
    if preferir_con_cable:
        con_cable = [(i, s) for i, s in puntuados if i["tc"]["con_cable"] is True]
        if con_cable:
            puntuados = con_cable
    puntuados.sort(key=lambda x: x[1], reverse=True)
    return [i for i, _ in puntuados[:3]]


def buscar_candidatos_tp(catalogo: list[dict], primario_requerido: float, ubicacion_requerida: str | None, burden_requerido: float | None = None) -> list[dict]:
    """La relación TP no depende de kVA, solo del nivel MT — se prefiere fase-neutro (√3/√3) con secundario 120V."""
    burden_requerido = 5.0 if burden_requerido is None else burden_requerido
    items = [i for i in catalogo if i["categoria"] == "Transformador de potencial"]

    def puntaje(item: dict) -> float:
        tp = item["tp"]
        if tp["burden"] != burden_requerido or tp["primario"] is None or abs(tp["primario"] - primario_requerido) > 1:
            return -1
        p = 3
        if tp["con_raiz_primario"] and tp["con_raiz_secundario"]:
            p += 3
        if tp["secundario"] == 120:
            p += 2
        if ubicacion_requerida and tp["ubicacion"]:
            p += 2 if tp["ubicacion"] == ubicacion_requerida else -2
        return p

    puntuados = sorted(([i, puntaje(i)] for i in items), key=lambda x: x[1], reverse=True)
    return [i for i, s in puntuados if s > 0][:3]


def buscar_candidatos_medidor(candidatos: list[dict], tipo_medida: str | None, elementos: int | None) -> list[dict]:
    def puntaje(item: dict) -> int:
        info = parsear_medidor(item["sku"])
        p = 0
        if tipo_medida and tipo_medida in info["tipos_medida"]:
            p += 2
        if info["fases"] is not None and elementos is not None and info["fases"] == elementos:
            p += 1
        return p

    return sorted(candidatos, key=puntaje, reverse=True)


def ordenar_candidatos_celda(candidatos: list[dict], tipo_medida: str, texto_hoja: str | None) -> list[dict]:
    """La similitud de texto con la hoja (×10) domina sobre la categoría por tipo de medida —
    una descripción real de ingeniería no debe perder contra la celda de MT más cara solo por
    la clasificación genérica."""
    import re

    palabras_hoja = [w for w in normText(normalizar_decimales(texto_hoja or "")).strip().split() if len(w) > 1] if texto_hoja else []

    def puntaje_texto(item: dict) -> int:
        if not palabras_hoja:
            return 0
        item_norm = normText(item["sku"])
        return sum(1 for w in palabras_hoja if w in item_norm)

    def puntaje(item: dict) -> int:
        es_ae_medida = bool(re.match(r"^celda ae-", item["sku"], re.I)) and item["categoria"] == "Celda de medida"
        es_caja_policarbonato = bool(re.search(r"caja|policarbonato", item["sku"], re.I)) or bool(re.search(r"caja|policarbonato", item["categoria"], re.I))
        if tipo_medida == "directa":
            if es_caja_policarbonato:
                return 3
            return 0 if (item["categoria"] == "Celda en MT" or es_ae_medida) else 1
        if tipo_medida == "indirecta":
            if item["categoria"] == "Celda en MT":
                return 3
            return 1 if es_ae_medida else 0
        return 3 if es_ae_medida else (0 if item["categoria"] == "Celda en MT" else 1)

    return sorted(candidatos, key=lambda i: puntaje_texto(i) * 10 + puntaje(i), reverse=True)


def resolver_tc_desde_hojas(norm_indirectas: dict | None, nt_cambio: dict | None, catalogo: list[dict], ubicacion: str | None, kv: float | None, alertas: list[str]) -> dict | None:
    """En orden: Normalizaciones_Indirectas (relación exacta), Data cambio NT (SKU
    descriptivo). None si ninguna hoja lo tiene — el llamador cae al cálculo por tablas CREG."""
    if norm_indirectas and norm_indirectas.get("tc_relacion"):
        ratio1 = extraer_ratio_de_texto(normalizar_decimales(norm_indirectas["tc_relacion"]))
        if ratio1:
            cand1 = buscar_candidatos_tc(catalogo, ratio1, ubicacion, kv)
            if cand1:
                cantidad = norm_indirectas.get("tc_cantidad")
                return {"item": cand1[0], "cantidad": cantidad if isinstance(cantidad, (int, float)) else None, "fuente": "Normalizaciones_Indirectas"}
            alertas.append(f'⚠ "Normalizaciones_Indirectas" indica TC "{norm_indirectas["tc_relacion"]}" para este CO, pero no encontré ese ítem exacto en el catálogo (ref_capex) — revisa si hay que agregarlo o si la relación real es otra.')
    if nt_cambio and nt_cambio.get("sku_tcs"):
        parsed = parsear_tc(normalizar_decimales(nt_cambio["sku_tcs"]))
        if parsed["ratio"]:
            cand2 = buscar_candidatos_tc(catalogo, parsed["ratio"], ubicacion, parsed["kv"] if parsed["kv"] is not None else kv, parsed["burden"])
            if cand2:
                return {"item": cand2[0], "cantidad": None, "fuente": "Data cambio NT", "texto_original": nt_cambio["sku_tcs"]}
        directo = normalizar_sku_contra_catalogo(catalogo, nt_cambio["sku_tcs"])
        if directo:
            return {"item": directo, "cantidad": None, "fuente": "Data cambio NT (texto)", "texto_original": nt_cambio["sku_tcs"]}
    return None


def resolver_tp_desde_hojas(norm_indirectas: dict | None, nt_cambio: dict | None, catalogo: list[dict], ubicacion: str | None, primario_esperado: float) -> dict | None:
    if norm_indirectas and norm_indirectas.get("tp_relacion"):
        parsed1 = parsear_tp(normalizar_decimales(str(norm_indirectas["tp_relacion"])))
        if parsed1["primario"] is not None:
            cand1 = buscar_candidatos_tp(catalogo, parsed1["primario"], ubicacion, parsed1["burden"])
            if cand1:
                cantidad = norm_indirectas.get("tp_cantidad")
                return {"item": cand1[0], "cantidad": cantidad if isinstance(cantidad, (int, float)) else None, "fuente": "Normalizaciones_Indirectas"}
    if nt_cambio and nt_cambio.get("sku_tps"):
        parsed2 = parsear_tp(normalizar_decimales(nt_cambio["sku_tps"]))
        if parsed2["primario"] is not None:
            cand2 = buscar_candidatos_tp(catalogo, parsed2["primario"], ubicacion, parsed2["burden"])
            if cand2:
                return {"item": cand2[0], "cantidad": None, "fuente": "Data cambio NT", "texto_original": nt_cambio["sku_tps"]}
        directo = normalizar_sku_contra_catalogo(catalogo, nt_cambio["sku_tps"])
        if directo:
            return {"item": directo, "cantidad": None, "fuente": "Data cambio NT (texto)", "texto_original": nt_cambio["sku_tps"]}
    return None
