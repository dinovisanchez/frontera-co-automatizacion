"""Qué equipo ya está instalado (según Metabase) y qué secciones parecen deficientes de
verdad. Puerto de equiposActualesMetabase/categoriaAlcanceDesdeTipoSku/
detectarSeccionesDeficientes/inferirCategoriaDesdeTexto/describirCondicionActual (Codigo.gs
líneas 255-263, 557-623, 414-535, 4771-4782).
"""

import re
from datetime import datetime

from core.services.catalogo_capex import parsear_tc, parsear_tp
from core.utils import quitar_acentos

_CATEGORIAS = ("medidor", "tc", "tp", "bloque_pruebas", "cable", "celda")


def categoria_alcance_desde_tipo_sku(tipo_sku: str | None, sku: str | None) -> str | None:
    """A diferencia de normalizeKindFromSku, separa TC de TP — para el cruce con el Alcance sí importa cuál es cuál."""
    t = quitar_acentos(f"{tipo_sku or ''} {sku or ''}").lower()

    if "medidor" in t:
        return "medidor"
    if "transformador de corriente" in t or re.search(r"\btc\b", t):
        return "tc"
    if "transformador de potencial" in t or "transformador de tension" in t or re.search(r"\btp\b", t):
        return "tp"
    if "bloque" in t:
        return "bloque_pruebas"
    if "cable" in t:
        return "cable"
    if "celda" in t:
        return "celda"
    return None


def _fecha(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def equipos_actuales_metabase(filas_metabase_co: list[dict]) -> dict:
    """{medidor, tc, tp, bloque_pruebas, cable, celda} -> cada uno None o {sku, marca, serial,
    estado_material, certificado_conformidad, certificado_calibracion, calibracion_vencida,
    calibracion_vencida_al_instalar, burdenes_desiguales?, ...}."""
    mas_reciente: dict[str, dict] = {}
    for r in filas_metabase_co:
        cat = categoria_alcance_desde_tipo_sku(r.get("tipo_sku"), r.get("sku"))
        if not cat:
            continue
        actual = mas_reciente.get(cat)
        if not actual or (_fecha(r.get("fecha_visita")) or datetime.min) > (_fecha(actual.get("fecha_visita")) or datetime.min):
            mas_reciente[cat] = r

    hoy = datetime.now()
    resultado: dict[str, dict | None] = {}
    for cat in _CATEGORIAS:
        r = mas_reciente.get(cat)
        if not r:
            resultado[cat] = None
            continue
        vto_calibracion = _fecha(r.get("vto_calibracion"))
        fecha_visita = _fecha(r.get("fecha_visita"))
        info = {
            "sku": r.get("sku") or "", "marca": r.get("marca") or "", "serial": r.get("serial") or "",
            "estado_material": r.get("estado_material") or "",
            "certificado_conformidad": bool(r.get("certificado_conformidad")), "vto_conformidad": r.get("vto_conformidad"),
            "certificado_calibracion": bool(r.get("certificado_calibracion")), "certificado_calibracion_url": r.get("certificado_calibracion"),
            "vto_calibracion": r.get("vto_calibracion"),
            "calibracion_vencida": bool(vto_calibracion and vto_calibracion < hoy),
            "calibracion_vencida_al_instalar": bool(vto_calibracion and fecha_visita and vto_calibracion < fecha_visita),
            "fecha_visita": r.get("fecha_visita"),
        }
        resultado[cat] = info

        if cat in ("tc", "tp"):
            parser = parsear_tc if cat == "tc" else parsear_tp
            misma_visita = [f for f in filas_metabase_co if categoria_alcance_desde_tipo_sku(f.get("tipo_sku"), f.get("sku")) == cat and f.get("visita_id") == r.get("visita_id")]
            burdenes = [parser(str(u.get("sku") or ""))["burden"] for u in misma_visita]
            burdenes = [b for b in burdenes if b is not None]
            burdenes_unicos = sorted(set(burdenes))
            if len(misma_visita) > 1 and len(burdenes_unicos) > 1:
                info["burdenes_desiguales"] = True
                info["burdenes_encontrados"] = burdenes_unicos
                info["num_unidades_instaladas"] = len(misma_visita)
            if len(misma_visita) > 1:
                alguna_vencida = any((_fecha(u.get("vto_calibracion")) or datetime.max) < (_fecha(u.get("fecha_visita")) or datetime.max) and u.get("vto_calibracion") and u.get("fecha_visita") for u in misma_visita)
                if alguna_vencida:
                    info["calibracion_vencida_al_instalar"] = True
    return resultado


_PALABRAS_PROBLEMA = ["mal estado", "sin certificado", "sin conformidad", "no cumple", "deteriorad", "danad", "obsolet", "incompleto", "no hay", "sin informacion", "requiere", "recomienda", "falta", "reemplaz", "debe instalar", "se debe"]
_NOMBRES_POR_CATEGORIA = {"medidor": ["medidor"], "tc": ["tc ", " tc", "transformador de corriente"], "tp": ["tp ", " tp", "transformador de potencial", "transformador de tension"], "bloque_pruebas": ["bloque de prueba"], "cable": ["cable"], "celda": ["celda"]}


def _menciona_problema(texto: str, categoria: str) -> bool:

    for nombre in _NOMBRES_POR_CATEGORIA[categoria]:
        idx = texto.find(nombre)
        while idx != -1:
            antes = texto[max(0, idx - 25):idx]
            es_posesivo_de_contenedor = bool(re.search(r"(celda|caja|gabinete|tablero)\s+(del|de la|de)\s*$", antes))
            if not es_posesivo_de_contenedor:
                ventana = texto[max(0, idx - 90):idx + 90]
                if any(p in ventana for p in _PALABRAS_PROBLEMA):
                    return True
            idx = texto.find(nombre, idx + 1)
    return False


def detectar_secciones_deficientes(equipos_actuales: dict, texto_observaciones: str | None, hay_acta_instalacion: bool) -> dict:
    """medidor/TC/TP: incompleto si el texto menciona un problema real, o si Metabase muestra
    certificado ausente / calibración vencida AL INSTALAR (nunca solo "vencida hoy", eso es
    normal). Bloque de pruebas: igual pero sin exigir calibración (no es instrumento de
    medida). Cable y Celda: SIEMPRE se marcan para revisión — Metabase nunca trae datos de
    estas dos y el texto del acta es una fuente demasiado inconsistente."""
    texto = quitar_acentos((texto_observaciones or "").lower())
    resultado: dict[str, bool] = {}
    for cat in _CATEGORIAS:
        if _menciona_problema(texto, cat):
            resultado[cat] = True
            continue
        if cat in ("medidor", "tc", "tp"):
            actual = equipos_actuales.get(cat)
            resultado[cat] = bool(
                not actual or actual["certificado_conformidad"] is False or actual["certificado_calibracion"] is False
                or actual.get("calibracion_vencida_al_instalar") is True or actual.get("burdenes_desiguales") is True
            )
            continue
        if cat == "bloque_pruebas":
            actual_bloque = equipos_actuales.get(cat)
            resultado[cat] = bool(not actual_bloque or actual_bloque["certificado_conformidad"] is False)
            continue
        if not hay_acta_instalacion:
            resultado[cat] = True
            continue
        resultado[cat] = True  # cable/celda: siempre se proponen para revisión (decisión explícita)
    return resultado


def inferir_categoria_desde_texto(texto: str | None) -> str | None:

    t = quitar_acentos((texto or "").lower())
    if "medidor" in t:
        return "medidor"
    if "celda" in t:
        return "celda"
    if "bloque" in t:
        return "bloque_pruebas"
    if "cable" in t:
        return "cable"
    if re.search(r"\btc\b", t) or "transformador de corriente" in t:
        return "tc"
    if re.search(r"\btp\b", t) or "transformador de potencial" in t or "transformador de tension" in t:
        return "tp"
    return None


def describir_condicion_actual(actual: dict | None) -> str:
    if not actual:
        return "(sin equipo previo registrado en Metabase)"
    base = []
    if actual.get("sku"):
        base.append(f'"{actual["sku"]}"')
    if actual.get("marca"):
        base.append(f"marca {actual['marca']}")
    if actual.get("serial"):
        base.append(f"serial {actual['serial']}")
    condiciones = []
    if actual.get("estado_material"):
        condiciones.append(f"estado: {actual['estado_material']}")
    condiciones.append("con conformidad" if actual["certificado_conformidad"] else "SIN conformidad")
    if actual["certificado_calibracion"]:
        condiciones.append(f"calibración VENCIDA ({actual['vto_calibracion']})" if actual["calibracion_vencida"] else "calibración vigente")
    else:
        condiciones.append("SIN calibración")
    return (", ".join(base) if base else "(sin marca/serial registrado)") + " — " + ", ".join(condiciones)
