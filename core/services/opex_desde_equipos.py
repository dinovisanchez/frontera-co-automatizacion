"""OPEX — deriva la propuesta de mano de obra del propio alcance de equipos CAPEX ya
calculado. Puerto de construirOpexDesdeEquipos (Codigo.gs líneas 5111-5203).

Es la ruta que generaliza a CUALQUIER CO (no depende de que alguien haya cargado el CO a
mano en "Consolidado"): recorre las filas de equipos que CAPEX ya propuso (TC/TP/medidor/
celda/cable/bloque de pruebas) y busca la maniobra de ref_tarifario más parecida a cada una,
con las mismas reglas de pareja instalar/desinstalar y extras de TC/TP en MT que la ruta
basada en "Consolidado".
"""

from dataclasses import dataclass, field

from core.services import tarifa_calculator as tc
from core.data_sources.sheets_client import SheetsClient

_ETIQUETA_CATEGORIA_OPEX = {"medidor": "Medidor", "tc": "TC", "tp": "TP", "bloque_pruebas": "Bloque de pruebas", "celda": "Celda"}


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
        'Este CO no está en "Consolidado" — estas maniobras se derivaron del propio alcance '
        'de equipos (TC/TP/medidor/celda/cable/bloque de pruebas), no del texto "Actividades MO". '
        "El carro canasta y el descargo no se pudieron calcular (esos dos valores solo existen "
        "en Consolidado) — revisa si aplican y agrégalos a mano."
    )
    alertas: list[str] = field(default_factory=list)


def construir_opex_desde_equipos(
    sheets: SheetsClient, co: str, or_raw: str, equipos_actuales: dict, filas_equipos: list[dict]
) -> ResultadoOpexDesdeEquipos:
    tarifario = tc.obtener_ref_tarifario_cacheado(sheets)
    operador = tc.normalizar_operador_tarifario(or_raw)

    resueltas: list[ManiobraResuelta] = []
    alertas: list[str] = []

    def agregar_si_nueva(nombre: str | None, cantidad: float, origen: str) -> None:
        if not nombre:
            return
        existente = next((m for m in resueltas if m.nombre == nombre), None)
        if existente:
            if origen == "extra-fija" and existente.origen != "extra-fija":
                existente.cantidad, existente.origen = (cantidad or 1), origen
            return
        resueltas.append(ManiobraResuelta(nombre=nombre, cantidad=cantidad or 1, origen=origen))

    for f in filas_equipos or []:
        cat = tc.categoria_desde_grupo_opex(f.get("grupo") or f.get("tipo") or "")
        if not cat:
            continue
        if cat == "cable":
            # "grupo" ("Cable señal"/"Cable desnudo") sí distingue cuál es cuál; "tipo" es
            # genérico ("Cable") para ambas filas — probarlo primero pierde la distinción
            # (bug real corregido en Codigo.gs, caso CO0100002908).
            texto_cable = f.get("grupo") or f.get("tipo")
            match_cable = tc.buscar_maniobra_mas_parecida(texto_cable, tarifario["maniobras"])
            if match_cable:
                agregar_si_nueva(match_cable, f.get("cantidad", 1), "equipo")
            else:
                alertas.append(f'No encontré en el tarifario una maniobra parecida a "{texto_cable}" — agrégala a mano.')
            continue

        palabras_clave = tc.PALABRAS_CLAVE_POR_CATEGORIA_OPEX.get(cat)
        query = tc.QUERY_MANIOBRA_POR_CATEGORIA_OPEX.get(cat)
        match = tc.buscar_maniobra_filtrada(tarifario["maniobras"], palabras_clave, query) if palabras_clave and query else None
        if match:
            agregar_si_nueva(match, f.get("cantidad", 1), "equipo")
        else:
            etiqueta = _ETIQUETA_CATEGORIA_OPEX.get(cat, cat)
            palabras_texto = '"/"'.join(palabras_clave or [])
            alertas.append(f'No encontré en el tarifario ninguna maniobra que mencione "{palabras_texto}" para {etiqueta} — agrégala a mano.')

    es_instalacion_nueva = not any(equipos_actuales.get(cat) for cat in ("medidor", "tc", "tp", "bloque_pruebas"))
    if not es_instalacion_nueva:
        for m in list(resueltas):
            contraparte = tc.contraparte_instalar_desinstalar(m.nombre, tarifario["maniobras"])
            if contraparte:
                agregar_si_nueva(contraparte, m.cantidad, "auto-pareja")

    hay_tc_tp_mt = any(tc.es_maniobra_tc_tp_mt(m.nombre) for m in resueltas)
    if hay_tc_tp_mt:
        resueltas[:] = [m for m in resueltas if not tc.normalizar_texto_opex(m.nombre).startswith("suspension reconexion")]
        agregar_si_nueva(tc.buscar_maniobra_mas_parecida("Apertura de portacircuito", tarifario["maniobras"]), 3, "extra-fija")
        agregar_si_nueva(tc.buscar_maniobra_mas_parecida("Revisión de frontera con OR u otro agente", tarifario["maniobras"]), 1, "extra-fija")
        if es_instalacion_nueva:
            agregar_si_nueva(tc.buscar_maniobra_mas_parecida("Cambio de DPS", tarifario["maniobras"]), 6, "extra-fija")
        else:
            agregar_si_nueva(tc.buscar_maniobra_mas_parecida("Calibración en sitio por equipo TCs - TPs MT", tarifario["maniobras"]), 6, "extra-fija")

    filas_salida = []
    for m in resueltas:
        precio_unitario = tarifario["precios"].get(m.nombre, {}).get(operador, 0.0)
        costo_total_mo = precio_unitario * m.cantidad
        filas_salida.append({
            "maniobra": m.nombre, "origen": m.origen, "operador": operador, "cantidad": m.cantidad,
            "costoUnitarioMO": precio_unitario, "costoTotalMO": costo_total_mo,
            "carroCanasta": 0, "descargo": 0, "acompanamiento": 0, "costoTotalConExtras": costo_total_mo,
        })

    total_general = sum(f["costoTotalConExtras"] for f in filas_salida)
    opcion = "Instalación nueva (derivado del alcance de equipos)" if es_instalacion_nueva else "Cambio de equipos (derivado del alcance de equipos)"

    return ResultadoOpexDesdeEquipos(
        co=co, operador=operador, or_original=or_raw, opcion_cumplimiento=opcion,
        filas=filas_salida, total_general=total_general, alertas=alertas,
    )
