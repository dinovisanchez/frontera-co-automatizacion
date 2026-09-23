"""CAPEX — clasifica el tipo de medida FINAL (CREG 038/2014). Puerto de clasificarTipoMedida
(Codigo.gs líneas 3638-3780) y sus 3 reglas de dominio (9a/9b/9c/9d del encargo de migración).

Alcance de este incremento: SOLO la clasificación de tipo de medida (directa/semidirecta/
indirecta) + el flag `reclasificado`. La propuesta de equipos concreta (SKUs de TC/TP/
medidor, construirPropuestaEquipos en el original) depende de más hojas de referencia
(ref_capex, Normalizaciones_Indirectas) que quedaron fuera de la confirmación inicial — se
migra en un siguiente incremento, no se improvisa acá.

`nt_cambio` / `norm_indirectas`: si el CO ya está en las hojas "Data cambio NT" o
"Normalizaciones_Indirectas" (libro "Quinquenales | Indirectas - Art.19"), el llamador pasa
ese dato ya resuelto — este módulo no sabe leer esas hojas, solo aplica la regla.
"""

from dataclasses import dataclass

from core.utils import quitar_acentos

UMBRAL_INDIRECTA_KVA = 225  # aclaración 2 CREG: por encima de esto, siempre indirecta.
UMBRAL_RECLASIFICACION_EXCLUSIVO_KVA = 15  # piso de Art.19 para exclusivo en BT.

TABLA1_UMBRAL_BT = {
    "120/208": {"semidirecta_min": 28},
    "127/220": {"semidirecta_min": 30},
    "254/440": {"semidirecta_min": 60},
    "120/240": {"semidirecta_min": 19},
}

_NIVELES_MT_RECONOCIDOS = {"13.2kV", "34.5kV", "11.4kV"}


@dataclass
class NtCambio:
    capacidad_kva: float | None = None
    tipo_medida: str | None = None


@dataclass
class ClasificacionMedida:
    tipo_medida_actual: str | None
    tipo_medida_final: str | None = None
    uso_transformador: str | None = None
    nivel_tension: str | None = None
    kva: float | None = None
    elementos: int | None = None
    # Número real de fases (1/2/3) para elegir el MODELO de medidor — separado de "elementos"
    # (2/3, solo para TC/TP) precisamente para no perder el caso monofásico. El acta nunca lo
    # trae directamente (no es parte del esquema de 14 campos); solo llega si el llamador lo
    # rellenó desde la hoja maestra (ver alcance_provisional.py) antes de clasificar.
    fases_medidor: int | None = None
    motivo: str = ""
    reclasificado: bool = False


def _nivel_mt_por_defecto(or_real: str | None) -> str:
    """Codigo.gs línea 3626: 11.4kV para Afinia/Air-e/Caribe, 13.2kV como estándar general."""
    compacto = "".join(c for c in quitar_acentos((or_real or "").lower()) if c.isalnum())
    if any(t in compacto for t in ("afinia", "aire", "caribe")):
        return "11.4kV"
    return "13.2kV"


def _nivel_tension_para_indirecta(nivel_actual: str | None, or_real: str | None) -> str:
    if nivel_actual in _NIVELES_MT_RECONOCIDOS:
        return nivel_actual
    return _nivel_mt_por_defecto(or_real)


def _rank_nivel_medida(tipo: str | None) -> int:
    return {"indirecta": 3, "semidirecta": 2, "directa": 1}.get(tipo, 0)


def clasificar_tipo_medida(
    spec: dict, nt_cambio: NtCambio | None, norm_indirectas: bool, or_real: str | None,
    trafo_compartido_confirmado: bool = False,
) -> ClasificacionMedida:
    """`trafo_compartido_confirmado`: el usuario confirmó a mano (checkbox del dictamen) que el
    transformador es COMPARTIDO — anula tanto el "exclusivo" que asumen "Data cambio NT"/
    "Normalizaciones_Indirectas" sin condición (Regla 9d-previa) como cualquier trafo_uso de la
    hoja maestra, para los casos en que el acta real (a veces ilegible/demasiado grande para
    OCR, ver CO0800000348, Dinovi 2026-09-23) o Lovable ya dejaron claro que es compartido y
    Art.19 no aplica. NO anula la Regla 9a (conexión YA en MT): eso es un hecho físico del
    punto de medición actual, no depende de si el transformador es compartido o no.
    """
    nivel_tension = spec.get("nivel_tension")
    trafo_uso = "compartido" if trafo_compartido_confirmado else spec.get("trafo_uso")
    if nt_cambio and nt_cambio.capacidad_kva is not None:
        kva_final = nt_cambio.capacidad_kva
    else:
        kva_final = spec.get("capacidad_instalada_kva") if isinstance(spec.get("capacidad_instalada_kva"), (int, float)) else None
    tipo_actual = ((nt_cambio.tipo_medida if nt_cambio else None) or spec.get("tipo_medida_actual") or "").lower() or None

    out = ClasificacionMedida(
        tipo_medida_actual=tipo_actual,
        uso_transformador=trafo_uso,
        nivel_tension=nivel_tension,
        kva=kva_final,
        elementos=spec.get("elementos_medida") if isinstance(spec.get("elementos_medida"), int) else None,
        fases_medidor=spec.get("fases_medidor") if isinstance(spec.get("fases_medidor"), int) else None,
    )

    # Regla 9d-previa (Codigo.gs 3661-3678): la sola presencia en "Data cambio NT" o
    # "Normalizaciones_Indirectas" YA es el dictamen — indirecta + exclusivo, sin condición...
    # salvo que el usuario ya haya confirmado a mano que es compartido (ver docstring).
    if (nt_cambio or norm_indirectas) and not trafo_compartido_confirmado:
        out.tipo_medida_final = "indirecta"
        out.uso_transformador = "exclusivo"
        out.nivel_tension = _nivel_tension_para_indirecta(out.nivel_tension, or_real)
        out.reclasificado = tipo_actual != "indirecta"
        fuente = "Data cambio NT" if nt_cambio else "Normalizaciones_Indirectas"
        out.motivo = (
            f'El CO está en "{fuente}" (libro "Quinquenales | Indirectas - Art.19") — esas hojas '
            "son solo para casos ya reclasificados a Indirecta por cambio de Nivel de Tensión "
            "(Art.19), transformador de uso exclusivo, sin importar lo que diga el acta o la hoja maestra."
        )
        return out
    if (nt_cambio or norm_indirectas) and trafo_compartido_confirmado:
        fuente = "Data cambio NT" if nt_cambio else "Normalizaciones_Indirectas"
        out.motivo = (
            f'El CO está en "{fuente}", que normalmente forzaría Indirecta + exclusivo — pero se '
            "confirmó a mano que el transformador es COMPARTIDO, así que Art.19 no aplica; se "
            f"evalúa como cualquier otro CO compartido a partir de aquí. Revisa por qué esa hoja "
            "trae este CO si de verdad es compartido (puede ser un error de esa hoja)."
        )
        # sigue evaluando las reglas normales de abajo con trafo_uso="compartido"

    # Regla 9a: conexión ya en MT (13.2/34.5/11.4kV) => indirecta + exclusivo por definición.
    es_mt = nivel_tension in _NIVELES_MT_RECONOCIDOS
    if tipo_actual == "indirecta" or es_mt:
        out.tipo_medida_final = "indirecta"
        out.uso_transformador = "exclusivo"
        out.nivel_tension = _nivel_tension_para_indirecta(out.nivel_tension, or_real)
        out.motivo = "Conexión en MT / medida indirecta: el transformador es de uso exclusivo por definición (Art. 19, CREG 038/2014)."
        out.reclasificado = tipo_actual != "indirecta"
        return out

    # Regla 9b/9c: transformador EXCLUSIVO en BT — solo sube a indirecta por encima del piso.
    if trafo_uso == "exclusivo":
        kva_exclusivo = kva_final
        if kva_exclusivo is not None and kva_exclusivo > UMBRAL_RECLASIFICACION_EXCLUSIVO_KVA:
            out.tipo_medida_final = "indirecta"
            out.reclasificado = True
            out.nivel_tension = _nivel_tension_para_indirecta(out.nivel_tension, or_real)
            out.motivo = (
                f"Transformador de uso exclusivo en BT ({kva_exclusivo} kVA > {UMBRAL_RECLASIFICACION_EXCLUSIVO_KVA} kVA): "
                "por Art.19 el punto de medición sube al lado de alta tensión → se reclasifica a Indirecta (Nivel de Tensión 2)."
            )
        elif kva_exclusivo is not None:
            out.tipo_medida_final = tipo_actual
            out.motivo = (
                f"Transformador de uso exclusivo en BT, pero de solo {kva_exclusivo} kVA "
                f"(≤ {UMBRAL_RECLASIFICACION_EXCLUSIVO_KVA} kVA) — no aplica el cambio de Nivel de Tensión a "
                "Indirecta por Art.19, se mantiene el tipo de medida indicado en el acta."
            )
        else:
            out.tipo_medida_final = tipo_actual
            out.motivo = (
                "Transformador de uso exclusivo en BT, pero no se conoce la capacidad instalada de este "
                f"cliente — el cambio de Nivel de Tensión a Indirecta (Art.19) solo aplica si supera "
                f"{UMBRAL_RECLASIFICACION_EXCLUSIVO_KVA} kVA; confirma la capacidad antes de decidir si aplica."
            )
        return out

    # Transformador COMPARTIDO: la capacidad es del transformador completo, no de este cliente.
    es_compartido = trafo_uso == "compartido"

    if out.kva is not None and out.kva > UMBRAL_INDIRECTA_KVA:
        if es_compartido:
            out.tipo_medida_final = tipo_actual
            out.motivo = (
                f"Transformador COMPARTIDO: los {out.kva} kVA son del transformador completo entre varios "
                f"usuarios, no de este cliente — no aplica el umbral de >225kVA sobre ese dato. Se mantiene "
                f"el tipo de medida indicado en el acta ({tipo_actual or '?'})."
            )
        else:
            out.tipo_medida_final = "indirecta"
            out.uso_transformador = "exclusivo"
            out.nivel_tension = _nivel_tension_para_indirecta(out.nivel_tension, or_real)
            out.motivo = f"Capacidad instalada > {UMBRAL_INDIRECTA_KVA} kVA: siempre medida indirecta (CREG 038/2014, aclaración 2), sin importar el nivel de tensión."
            out.reclasificado = tipo_actual != "indirecta"
        return out

    umbral = TABLA1_UMBRAL_BT.get(nivel_tension)
    if umbral and out.kva is not None and es_compartido:
        out.tipo_medida_final = tipo_actual
        out.motivo = (
            f"Transformador COMPARTIDO: los {out.kva} kVA son del transformador completo entre varios "
            f"usuarios, no de este cliente — no se puede aplicar Tabla 1 sobre ese dato. Se mantiene el "
            f"tipo de medida indicado en el acta ({tipo_actual or '?'})."
        )
    elif umbral and out.kva is not None:
        # La clasificación SOLO SUBE (directa < semidirecta < indirecta), nunca se degrada.
        por_tabla1 = "semidirecta" if out.kva >= umbral["semidirecta_min"] else "directa"
        if _rank_nivel_medida(tipo_actual) > _rank_nivel_medida(por_tabla1):
            out.tipo_medida_final = tipo_actual
            out.motivo = (
                f"Ya está en {tipo_actual}, un nivel más alto que lo que exigiría Tabla 1 CREG 038/2014 "
                f"para {nivel_tension} con la capacidad actual ({out.kva} kVA, umbral {umbral['semidirecta_min']} kVA) "
                "— la clasificación de medida nunca se degrada, solo sube."
            )
        else:
            out.tipo_medida_final = por_tabla1
            out.motivo = f"Según Tabla 1 CREG 038/2014 para {nivel_tension} (umbral {umbral['semidirecta_min']} kVA)."
    else:
        out.tipo_medida_final = tipo_actual
        out.motivo = "No hay suficiente información (nivel de tensión o capacidad instalada) para aplicar la Tabla 1; se mantiene lo indicado en el acta."

    return out
