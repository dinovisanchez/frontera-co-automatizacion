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

    def extra_fija_mt(self) -> None:
        self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["apertura", "portacircuito"]), 3, "extra-fija", "apertura de portacircuito")
        self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["revision", "frontera"]), 1, "extra-fija", "revisión de frontera con OR")
        if self.es_instalacion_nueva:
            self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["cambio", "dps"]), 6, "extra-fija", "cambio de DPS")
        else:
            self._agregar(tc.buscar_maniobra_por_palabras(self.maniobras_reales, ["calibracion", "sitio", "tcs", "tps", "mt"]), 6, "extra-fija", "calibración en sitio TCs-TPs MT")


def _resolver_medidor(r: _Resolver, tipo_medida: str, ubicacion: str | None, con_bloque: bool) -> None:
    if ubicacion not in ("interior", "exterior"):
        r.alertas.append('No se conoce la ubicación (interior/exterior) de la medida — no se puede tarifar el medidor, agrégalo a mano.')
        return
    if tipo_medida == "directa":
        r.con_contraparte(["instalacion", "medida", "directa", ubicacion], ["retiro", "medida", "directa", ubicacion], 1, "medidor (directa)")
    elif tipo_medida == "semidirecta":
        if con_bloque:
            r.con_contraparte(["instalacion", "semidirecta", "bloque", ubicacion], ["retiro", "semidirecta", "bloque"], 1, "medidor + bloque (semidirecta)")
        else:
            r.con_contraparte(["instalacion", "medidor", "semidirecta", ubicacion], ["retiro", "medidor", "semidirecta", ubicacion], 1, "medidor (semidirecta)", excluidas_inst=["bloque"])
    elif tipo_medida == "indirecta":
        r.con_contraparte(["instalacion", "indirecta", ubicacion], ["retiro", "indirecta", ubicacion], 1, "medidor + bloque de pruebas (indirecta)")


def _resolver_tc_tp(r: _Resolver, tipo_medida: str, ubicacion: str | None, hay_tc: bool, hay_tp: bool) -> bool:
    """Devuelve True si se agregó algo de TC/TP en MT (dispara extra_fija_mt)."""
    if tipo_medida == "semidirecta" and hay_tc:
        r.con_contraparte(["instalacion", "tcs", "semidirecta"], ["retiro", "tcs", "semidirecta"], 1, "TCs (semidirecta)")
        return False  # TCs en semidirecta NO son MT — no aplican los extras de portacircuito/DPS/calibración

    if tipo_medida != "indirecta" or not (hay_tc or hay_tp):
        return False
    if ubicacion not in ("interior", "exterior"):
        r.alertas.append("No se conoce la ubicación (interior/exterior) — no se puede tarifar el montaje de TC/TP en MT, agrégalo a mano.")
        return False
    if hay_tc:
        r.con_contraparte(["montaje", "tcs", "mt", ubicacion], ["desmonte", "tcs", "mt", ubicacion], 1, "TCs en MT")
    if hay_tp:
        r.con_contraparte(["montaje", "tps", "mt", ubicacion], ["desmonte", "tps", "mt", ubicacion], 1, "TPs en MT")
    return True


def construir_opex_desde_equipos(
    sheets: SheetsClient, co: str, or_raw: str, tipo_medida_final: str, ubicacion: str | None,
    secciones: dict, es_instalacion_nueva: bool, filas_cable: list[dict] | None = None,
) -> ResultadoOpexDesdeEquipos:
    tarifario = tc.obtener_ref_tarifario_cacheado(sheets)
    operador = tc.normalizar_operador_tarifario(or_raw)
    alertas: list[str] = []
    r = _Resolver(tarifario["maniobras"], es_instalacion_nueva, alertas)

    if secciones.get("medidor") or secciones.get("bloque_pruebas"):
        _resolver_medidor(r, tipo_medida_final, ubicacion, con_bloque=bool(secciones.get("bloque_pruebas")))

    hubo_mt = _resolver_tc_tp(r, tipo_medida_final, ubicacion, bool(secciones.get("tc")), bool(secciones.get("tp")))
    if hubo_mt:
        r.extra_fija_mt()

    if secciones.get("celda"):
        alertas.append('"Celda" no tiene ninguna maniobra propia en ref_tarifario — agrégala a mano.')

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
    )
