"""OPEX — deriva la propuesta de mano de obra del alcance de equipos que ya calculó CAPEX
(tipo de medida final + ubicación + qué secciones cambian), en vez de leer "Actividades MO"
de Consolidado.

REDISEÑADO (Dinovi, 2026-09-21) tras verificar la hoja real de ref_tarifario (gid 192919919):
las 72 maniobras están armadas por TIPO DE MEDIDA × UBICACIÓN, no por categoría de equipo
suelta — ej. "Instalación semidirecta interior (medidor + bloque + módem + toma 110V si
aplica)" cubre medidor+bloque JUNTOS en una sola maniobra, y "Montaje TCs MT (1–3) – exterior"
es un precio plano por visita (1 a 3 unidades), no por unidad. "Celda" y "Cable" no tienen
NINGUNA maniobra propia en esta hoja — siempre quedan como alerta para agregar a mano, eso es
correcto, no un bug.

Cada combinación de palabras clave de abajo fue verificada leyendo la hoja real fila por fila
(no es una plantilla genérica adivinada) — ver tarifa_calculator.buscar_maniobra_por_palabras.
"""

from dataclasses import dataclass, field

from core.data_sources.sheets_client import SheetsClient
from core.services import tarifa_calculator as tc


@dataclass
class ManiobraResuelta:
    nombre: str
    cantidad: float
    origen: str  # 'equipo' | 'auto-pareja' | 'extra-fija'


@dataclass
class ResultadoOpexDesdeEquipos:
    co: str
    operador: str
    or_original: str
    opcion_cumplimiento: str
    filas: list[dict] = field(default_factory=list)
    total_general: float = 0.0
    derivado_de_equipos: bool = True
    # Los 72 nombres reales de ref_tarifario (Dinovi, 2026-09-23) — el frontend los usa para
    # armar el desplegable de "agregar fila manual" en vez de exigir que el usuario teclee el
    # nombre EXACTO a mano (única forma de que la fila agregada traiga costo real).
    maniobras_disponibles: list[str] = field(default_factory=list)
    nota: str = (
        'Este CO no está en "Consolidado" — estas maniobras se derivaron del tipo de medida '
        "final y la ubicación que ya calculó CAPEX. Celda y cable no tienen maniobra propia en "
        "ref_tarifario — revisa si aplican y agrégalas a mano."
    )
    alertas: list[str] = field(default_factory=list)


class _Resolver:
    def __init__(self, maniobras_reales: list[str], es_instalacion_nueva: bool, alertas: list[str]):
        self.maniobras_reales = maniobras_reales
        self.es_instalacion_nueva = es_instalacion_nueva
        self.alertas = alertas
        self.resueltas: list[ManiobraResuelta] = []

    def _agregar(self, nombre: str | None, cantidad: float, origen: str, etiqueta_error: str) -> None:
        if not nombre:
            self.alertas.append(f'No encontré (de forma inequívoca) la maniobra de "{etiqueta_error}" en ref_tarifario — revisa la hoja, puede haber cambiado, y agrégala a mano.')
            return
        if any(m.nombre == nombre for m in self.resueltas):
            return
        self.resueltas.append(ManiobraResuelta(nombre=nombre, cantidad=cantidad, origen=origen))

    def agregar_directo(self, nombre: str | None, cantidad: float, origen: str, etiqueta_error: str) -> None:
        self._agregar(nombre, cantidad, origen, etiqueta_error)

    def con_contraparte(self, requeridas_inst: list[str], requeridas_ret: list[str] | None, cantidad: int, etiqueta: str, excluidas_inst: list[str] | None = None) -> None:
        inst = tc.buscar_maniobra_por_palabras(self.maniobras_reales, requeridas_inst, excluidas_inst)
        self._agregar(inst, cantidad, "equipo", f"instalación/montaje de {etiqueta}")
        if not self.es_instalacion_nueva and requeridas_ret is not None:
            ret = tc.buscar_maniobra_por_palabras(self.maniobras_reales, requeridas_ret)
            self._agregar(ret, cantidad, "auto-pareja", f"retiro/desmonte de {etiqueta}")

    def revision_frontera_si_cambio(self) -> None:
        """"Revisión de frontera con OR" (Dinovi, 2026-09-22): sale en CUALQUIER cambio de
        equipo (retiro+instalación), sin importar el tipo de medida — el OR debe estar
        presente. NO depende de que haya trabajo de TC/TP en MT (a diferencia de
        extra_fija_mt): una instalación nueva no la necesita, un cambio siempre sí.
        """
        if self.es_instalacion_nueva:
            return
        self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["revision", "frontera"]), 1, "extra-fija", "revisión de frontera con OR")

    def extra_fija_mt(self, ubicacion: str | None) -> None:
        """Extras que solo aplican cuando hay trabajo de TC/TP en Indirecta (MT)."""
        self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["apertura", "portacircuito"]), 3, "extra-fija", "apertura de portacircuito")
        if ubicacion == "exterior":
            self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["cambio", "crucetas", "mt", "exterior"]), 1, "extra-fija", "cambio de crucetas en MT (exterior)")
            # Confirmado por Dinovi, 2026-09-23: extra fija en exterior, igual patrón que las
            # crucetas (misma línea de arriba) — 3 unidades por visita.
            self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["cambio", "pararrayos"]), 3, "extra-fija", "cambio de pararrayos")
        if self.es_instalacion_nueva:
            self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["cambio", "dps"]), 6, "extra-fija", "cambio de DPS")
        else:
            self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["calibracion", "sitio", "tcs", "tps", "mt"]), 6, "extra-fija", "calibración en sitio TCs-TPs MT")


def _palabras_medidor(tipo_medida: str, ubicacion: str, accion: str, con_bloque: bool) -> list[str]:
    """`accion`: "instalacion" | "retiro" — mismas palabras clave de con_contraparte (cada
    combinación verificada fila por fila contra la hoja real), separadas por acción para poder
    mezclar un tipo de medida en instalación y OTRO en retiro (cambio de nivel de tensión: se
    instala lo nuevo, pero se retira lo que había antes). OJO: "retiro semidirecta con bloque"
    NO lleva ubicación en la hoja real (a diferencia de todas las demás) — no es un descuido."""
    if tipo_medida == "directa":
        return [accion, "medida", "directa", ubicacion]
    if tipo_medida == "semidirecta":
        if con_bloque:
            return [accion, "semidirecta", "bloque"] if accion == "retiro" else [accion, "semidirecta", "bloque", ubicacion]
        return [accion, "medidor", "semidirecta", ubicacion]
    return [accion, "indirecta", ubicacion]  # indirecta siempre trae medidor+bloque juntos


def _resolver_medidor(r: _Resolver, tipo_medida_final: str, tipo_medida_actual: str | None, ubicacion: str | None, con_bloque: bool) -> None:
    if ubicacion not in ("interior", "exterior"):
        r.alertas.append('No se conoce la ubicación (interior/exterior) de la medida — no se puede tarifar el medidor, agrégalo a mano.')
        return

    excluidas_inst = ["bloque"] if (tipo_medida_final == "semidirecta" and not con_bloque) else None
    inst = tc.buscar_maniobra_por_palabras(r.maniobras_reales, _palabras_medidor(tipo_medida_final, ubicacion, "instalacion", con_bloque), excluidas_inst)
    r.agregar_directo(inst, 1, "equipo", f"instalación de medidor ({tipo_medida_final})")

    if r.es_instalacion_nueva:
        return
    # Cambio de nivel de tensión (reclasificado): lo que se RETIRA es el equipo del tipo de
    # medida ACTUAL (antes del cambio), no del final — ej. si hoy es directa y pasa a
    # indirecta, el retiro es "Retiro directa", no "Retiro indirecta" (Dinovi, 2026-09-22).
    tipo_retiro = tipo_medida_actual or tipo_medida_final
    ret = tc.buscar_maniobra_por_palabras(r.maniobras_reales, _palabras_medidor(tipo_retiro, ubicacion, "retiro", con_bloque))
    r.agregar_directo(ret, 1, "auto-pareja", f"retiro de medidor ({tipo_retiro})")


# CO0800001175 (Dinovi, 2026-09-23): "Instalación indirecta exterior: medidor + BP + módem +
# toma 110 V (sin Montaje  TCs/TPs MT)" también contiene las palabras "montaje"/"tcs"/"tps"/
# "mt"/ubicación (las menciona para ACLARAR que esa maniobra NO las incluye) — eso empataba
# con la búsqueda real de "Montaje TCs/TPs MT" y la volvía ambigua (2 candidatas → None), así
# que nunca se proponía el montaje aunque la hoja SÍ tiene una fila propia para eso.
_EXCLUIDAS_MONTAJE_TC_TP = ["instalacion"]


def _resolver_tc_tp(r: _Resolver, tipo_medida_final: str, tipo_medida_actual: str | None, ubicacion: str | None, hay_tc: bool, hay_tp: bool) -> bool:
    """Devuelve True si se agregó algo de TC/TP en MT (dispara extra_fija_mt).

    `tipo_medida_actual`: igual criterio que _resolver_medidor — el retiro depende de lo que
    había ANTES del cambio, no del tipo final. Confirmado por Dinovi, 2026-09-22: al pasar de
    semidirecta a indirecta (cambio de nivel de tensión), el TC de semidirecta es de BT, no de
    MT — "desmonte TCs MT" no aplica, es "retiro TCs semidirecta". TP nunca existió en
    semidirecta/directa, así que si viene de ahí no hay ningún TP que retirar.
    """
    tipo_retiro = tipo_medida_actual or tipo_medida_final

    if tipo_medida_final == "semidirecta" and hay_tc:
        r.con_contraparte(["instalacion", "tcs", "semidirecta"], ["retiro", "tcs", "semidirecta"], 1, "TCs (semidirecta)")
        return False  # TCs en semidirecta NO son MT — no aplican los extras de portacircuito/DPS/calibración

    if tipo_medida_final != "indirecta" or not (hay_tc or hay_tp):
        return False
    if ubicacion not in ("interior", "exterior"):
        r.alertas.append("No se conoce la ubicación (interior/exterior) — no se puede tarifar el montaje de TC/TP en MT, agrégalo a mano.")
        return False

    ya_era_indirecta = tipo_retiro == "indirecta"  # solo entonces había TC/TP en MT para desmontar

    if hay_tc:
        if ya_era_indirecta:
            r.con_contraparte(["montaje", "tcs", "mt", ubicacion], ["desmonte", "tcs", "mt", ubicacion], 1, "TCs en MT", _EXCLUIDAS_MONTAJE_TC_TP)
        else:
            r.agregar_directo(tc.buscar_maniobra_por_palabras(r.maniobras_reales, ["montaje", "tcs", "mt", ubicacion], _EXCLUIDAS_MONTAJE_TC_TP), 1, "equipo", "montaje de TCs en MT")
            if not r.es_instalacion_nueva and tipo_retiro == "semidirecta":
                r.agregar_directo(tc.buscar_maniobra_por_palabras(r.maniobras_reales, ["retiro", "tcs", "semidirecta"]), 1, "auto-pareja", "retiro de TCs (semidirecta, pasa a MT)")
    if hay_tp:
        if ya_era_indirecta:
            r.con_contraparte(["montaje", "tps", "mt", ubicacion], ["desmonte", "tps", "mt", ubicacion], 1, "TPs en MT", _EXCLUIDAS_MONTAJE_TC_TP)
        else:
            r.agregar_directo(tc.buscar_maniobra_por_palabras(r.maniobras_reales, ["montaje", "tps", "mt", ubicacion], _EXCLUIDAS_MONTAJE_TC_TP), 1, "equipo", "montaje de TPs en MT")
            # tipo_retiro directa/semidirecta: TP nunca existió antes, no hay nada que retirar
    return True


def _resolver_gabinete(r: _Resolver, tipo_medida_final: str, tipo_medida_actual: str | None, ubicacion: str | None, celda_sku: str | None = None) -> None:
    """En Directa, "Celda" en CAPEX es en realidad un gabinete de medida (metálico o
    policarbonato) — confirmado por Dinovi, 2026-09-22: SÍ existe maniobra propia en
    ref_tarifario ("Instalación gabinete de medida... sobrepuesto interior/exterior"), a
    diferencia de semidirecta/indirecta donde "Celda" de verdad no tiene ninguna.

    Montaje (Dinovi, 2026-09-23, CO0800001175): si el SKU de celda ya dice "poste" o
    "fachada" (ej. "Celda para medidor y Bornera de POSTE" — el texto real que trae "Data
    cambio NT" para este caso), se usa la maniobra puntual "... exterior (fachada/poste)" —
    la misma línea cubre metálico Y policarbonato, así que no hace falta distinguir material.
    Si no hay esa pista, se asume "sobrepuesto" (el más común) y se alerta para confirmar.
    """
    if tipo_medida_final != "directa":
        return
    if ubicacion not in ("interior", "exterior"):
        r.alertas.append('No se conoce la ubicación (interior/exterior) — no se puede tarifar el gabinete, agrégalo a mano.')
        return

    es_poste = bool(celda_sku) and ("poste" in celda_sku.lower() or "fachada" in celda_sku.lower())
    if es_poste:
        inst = tc.buscar_maniobra_por_palabras(r.maniobras_reales, ["instalacion", "gabinete", "fachada"])
        r.agregar_directo(inst, 1, "equipo", "instalación de gabinete (fachada/poste)")
    else:
        inst = tc.buscar_maniobra_por_palabras(r.maniobras_reales, ["instalacion", "gabinete", "sobrepuesto", ubicacion])
        r.agregar_directo(inst, 1, "equipo", f"instalación de gabinete ({ubicacion})")
        if inst:
            r.alertas.append('ℹ️ Se asumió gabinete "sobrepuesto" para tarifar la instalación — si en realidad es empotrado o el especial de fachada/poste, ajusta la maniobra a mano en la hoja OPEX.')

    tipo_retiro = tipo_medida_actual or tipo_medida_final
    if not r.es_instalacion_nueva and tipo_retiro == "directa":
        # El retiro solo aplica si YA había un gabinete de directa antes (si viene de otro tipo
        # de medida, nunca hubo gabinete que retirar).
        ret = tc.buscar_maniobra_por_palabras(r.maniobras_reales, ["retiro", "gabinete", ubicacion])
        r.agregar_directo(ret, 1, "auto-pareja", f"retiro de gabinete ({ubicacion})")


def _resolver_gabinete_mt(r: _Resolver, celda_sku: str | None) -> None:
    """En semidirecta/indirecta, "Celda" normalmente NO tiene maniobra propia en
    ref_tarifario (confirmado leyendo la hoja real) — EXCEPCIÓN encontrada por Dinovi,
    2026-09-23 (CO0800001175): el modelo "Celda AE-325" (categoría "Celda en MT" del
    catálogo CAPEX) sí tiene su propia línea, y viene COMBINADA (instalación + retiro en una
    sola maniobra, a diferencia del resto de gabinetes que sí se separan). Si el SKU de celda
    elegido en CAPEX no es ese modelo puntual, se mantiene la alerta de agregar a mano — no
    hay evidencia de que otras variantes de celda en MT tengan maniobra propia.
    """
    if celda_sku and "325" in celda_sku:
        match = tc.buscar_maniobra_por_palabras(r.maniobras_reales, ["gabinete", "325"])
        r.agregar_directo(match, 1, "equipo", "instalación y retiro de gabinete AE-325")
        return
    r.alertas.append('"Celda" no tiene ninguna maniobra propia en ref_tarifario — agrégala a mano.')


def construir_opex_desde_equipos(
    sheets: SheetsClient, co: str, or_raw: str, tipo_medida_final: str, ubicacion: str | None,
    secciones: dict, es_instalacion_nueva: bool, filas_cable: list[dict] | None = None,
    tipo_medida_actual: str | None = None, celda_sku: str | None = None,
) -> ResultadoOpexDesdeEquipos:
    """`tipo_medida_actual`: tipo de medida ANTES del cambio (ej. "directa"/"semidirecta") —
    solo importa cuando difiere de `tipo_medida_final` (cambio de nivel de tensión/Art.19):
    ahí el retiro es del equipo que había, no del que se va a instalar. Si no se pasa, se
    asume igual al final (mismo comportamiento que antes de este parámetro)."""
    tarifario = tc.obtener_ref_tarifario_cacheado(sheets)
    operador = tc.normalizar_operador_tarifario(or_raw)
    alertas: list[str] = []
    r = _Resolver(tarifario["maniobras"], es_instalacion_nueva, alertas)

    if secciones.get("medidor") or secciones.get("bloque_pruebas"):
        _resolver_medidor(r, tipo_medida_final, tipo_medida_actual, ubicacion, con_bloque=bool(secciones.get("bloque_pruebas")))

    hubo_mt = _resolver_tc_tp(r, tipo_medida_final, tipo_medida_actual, ubicacion, bool(secciones.get("tc")), bool(secciones.get("tp")))
    if hubo_mt:
        r.extra_fija_mt(ubicacion)

    r.revision_frontera_si_cambio()

    if secciones.get("celda"):
        if tipo_medida_final == "directa":
            _resolver_gabinete(r, tipo_medida_final, tipo_medida_actual, ubicacion, celda_sku)
        else:
            _resolver_gabinete_mt(r, celda_sku)

    for f in filas_cable or []:
        texto_cable = f.get("grupo") or f.get("tipo")
        match_cable = tc.buscar_maniobra_mas_parecida(texto_cable, tarifario["maniobras"])
        if match_cable:
            r.agregar_directo(match_cable, f.get("cantidad", 1), "equipo", str(texto_cable))
        else:
            alertas.append(f'No encontré en el tarifario ninguna maniobra para "{texto_cable}" (cable no tiene línea propia en esta hoja) — agrégala a mano.')

    filas_salida = []
    for m in r.resueltas:
        precio_unitario = tarifario["precios"].get(m.nombre, {}).get(operador, 0.0)
        costo_total_mo = precio_unitario * m.cantidad
        filas_salida.append({
            "maniobra": m.nombre, "origen": m.origen, "operador": operador, "cantidad": m.cantidad,
            "costoUnitarioMO": precio_unitario, "costoTotalMO": costo_total_mo,
            "carroCanasta": 0, "descargo": 0, "acompanamiento": 0, "costoTotalConExtras": costo_total_mo,
        })

    total_general = sum(f["costoTotalConExtras"] for f in filas_salida)
    opcion = "Instalación nueva (derivado del alcance CAPEX)" if es_instalacion_nueva else "Cambio de equipos (derivado del alcance CAPEX)"

    return ResultadoOpexDesdeEquipos(
        co=co, operador=operador, or_original=or_raw, opcion_cumplimiento=opcion,
        filas=filas_salida, total_general=total_general, alertas=alertas,
        maniobras_disponibles=sorted(tarifario["maniobras"]),
    )
