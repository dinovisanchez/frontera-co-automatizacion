"""Arma el `ctx` que comparten todos los resolutores de propuesta_equipos.py — puerto de la
parte de "preparación" de construirPropuestaEquipos (Codigo.gs líneas 4140-4256): cuántos
elementos de medida hay, qué ya trae "Data cambio NT"/"Normalizaciones_Indirectas" para
celda/medidor/bloque, si el transformador es compartido en BT (para no recalcular TC por una
capacidad que no es de este cliente), y la clase de tensión a usar para buscar el TC.
"""

from core.services.catalogo_capex import normalizar_medidor_contra_catalogo, normalizar_sku_contra_catalogo
from core.services.resolucion_tc_tp import preferir_con_cable_por_or


def _armar_contexto(
    diagnostico: dict, spec: dict, catalogo: list[dict], dictamen: dict, equipos_actuales: dict,
    nt_cambio: dict | None, norm_indirectas: dict | None, relacion_certificada_tc: dict | None, or_real: str | None,
) -> dict:
    tipo_medida = diagnostico["tipo_medida_final"]
    nivel = diagnostico["nivel_tension"]
    ubicacion = spec.get("ubicacion_medida")
    faltan = dictamen.get("secciones") or {}

    # 3 elementos por defecto (trifásico tetrafilar) salvo que el acta/hoja diga 2 — pero si
    # Indirecta viene de RECLASIFICAR un esquema Semidirecta/BT (Art.19), siempre se fuerza el
    # set completo de 3: al subir el punto de medición a MT se instala metering tetrafilar
    # completo, no se hereda el esquema de abajo.
    elementos = 3 if (tipo_medida == "indirecta" and diagnostico["reclasificado"]) else (diagnostico.get("elementos") or 3)
    fases_medidor = diagnostico.get("fases_medidor") if isinstance(diagnostico.get("fases_medidor"), int) else elementos

    if diagnostico["reclasificado"]:
        # Lovable marcó "Completo" bajo el esquema anterior — ya no aplica: al pasar a
        # Indirecta el set completo de medida cambia (TP no existía, celda es nueva para MT).
        faltan = {"medidor": faltan.get("medidor"), "tc": True, "tp": True, "bloque_pruebas": True, "cable": True, "celda": True}

    celda_texto = (norm_indirectas and norm_indirectas.get("celda")) or (nt_cambio and nt_cambio.get("celda")) or None
    celda_fuente = "Normalizaciones_Indirectas" if (norm_indirectas and norm_indirectas.get("celda")) else ("Data cambio NT" if (nt_cambio and nt_cambio.get("celda")) else None)
    celda_nt = normalizar_sku_contra_catalogo(catalogo, celda_texto) if celda_texto else None

    medidor_nt = medidor_texto = medidor_fuente = None
    if norm_indirectas and norm_indirectas.get("medidor"):
        candidato = normalizar_medidor_contra_catalogo(catalogo, norm_indirectas["medidor"], tipo_medida)
        if candidato:
            medidor_nt, medidor_texto, medidor_fuente = candidato, norm_indirectas["medidor"], "Normalizaciones_Indirectas"
    if not medidor_nt and nt_cambio and nt_cambio.get("medidor"):
        candidato = normalizar_medidor_contra_catalogo(catalogo, nt_cambio["medidor"], tipo_medida)
        if candidato:
            medidor_nt, medidor_texto, medidor_fuente = candidato, nt_cambio["medidor"], "Data cambio NT"

    bloque_texto = (nt_cambio and nt_cambio.get("tipo_bloque")) or None
    bloque_nt = normalizar_sku_contra_catalogo(catalogo, bloque_texto) if bloque_texto else None

    # Transformador COMPARTIDO en BT: la capacidad instalada del acta es la del transformador
    # completo, NO la base correcta para dimensionar el TC de este cliente — no aplica cuando
    # ya es Indirecta (ahí la medida SÍ es del cliente, es su propio punto en MT).
    es_compartido_bt = diagnostico["uso_transformador"] == "compartido" and tipo_medida != "indirecta"

    kv_clase_tc = 0.72 if tipo_medida == "semidirecta" else (36 if nivel == "34.5kV" else 17.5)
    nivel_tiene_tabla_oficial = nivel in ("13.2kV", "34.5kV")

    estado_cable = {"con_cable": False}

    def marcar_si_con_cable(item: dict | None) -> None:
        if item and item.get("tc") and item["tc"].get("con_cable"):
            estado_cable["con_cable"] = True

    return {
        "diagnostico": diagnostico, "spec": spec, "catalogo": catalogo, "dictamen": dictamen,
        "equipos_actuales": equipos_actuales, "nt_cambio": nt_cambio, "norm_indirectas": norm_indirectas,
        "relacion_certificada_tc": relacion_certificada_tc, "or": or_real,
        "ubicacion": ubicacion, "faltan": faltan, "elementos": elementos, "fases_medidor": fases_medidor,
        "celda_texto": celda_texto, "celda_fuente": celda_fuente, "celda_nt": celda_nt,
        "medidor_nt": medidor_nt, "medidor_texto": medidor_texto, "medidor_fuente": medidor_fuente,
        "bloque_texto": bloque_texto, "bloque_nt": bloque_nt,
        "es_compartido_bt": es_compartido_bt, "kv_clase_tc": kv_clase_tc, "nivel_tiene_tabla_oficial": nivel_tiene_tabla_oficial,
        "preferir_con_cable": preferir_con_cable_por_or(or_real),
        "marcar_si_con_cable": marcar_si_con_cable,
        # `ubicacion` puede reasignarse en caliente al resolver TC (ver _propagar_ubicacion_desde_tc
        # en propuesta_equipos.py) — por eso el resto de resolutores debe LEER ctx["ubicacion"]
        # en el momento de usarlo, nunca capturar el valor de este dict al vuelo. Lo mismo aplica
        # a "tc_seleccionado_con_cable": es una property, no un valor congelado al armar el ctx,
        # porque marcar_si_con_cable() la actualiza DESPUÉS de que se resuelve el TC.
        "_estado_cable": estado_cable,
    }
