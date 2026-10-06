"""Comparación masiva de ~400 CO contra "Data cambio NT"/"Normalizaciones_Indirectas" (Dinovi,
2026-09-24) — mismo patrón de "un paso por invocación + polling" que job_store.py/
actas_start.py/actas_step.py, pero a nivel de LOTE: cada paso avanza UNA acta de UN CO del lote
(o corre el análisis final de ese CO cuando ya no le faltan actas), nunca el lote completo de
una sola vez — 400 CO no caben en una sola invocación de Vercel (maxDuration 60s).

Reutiliza el job de actas EXISTENTE por CO (EstadoJob de job_store.py,
alcance_combiner.procesar_siguiente_acta) en vez de reinventar el seguimiento de progreso —
solo cambia dónde se persiste (una fila por CO en "PyLoteAlcance" en vez de una fila por CO en
"PyAsyncJobs", porque acá conviven muchos CO bajo un mismo lote_id).

Modo de lectura de actas automático (permitir_modo_imagen=True, Dinovi 2026-09-24): igual que
el flujo CO-por-CO — intenta texto (OCR) primero, y solo cae al PDF completo (con imágenes)
si el texto no bastó y el archivo cabe bajo el límite de tamaño; no se fuerza a texto-only.
"""

import json
import time
import uuid
from dataclasses import dataclass

from core.data_sources.sheets_client import SheetsClient, con_reintento_sheets, es_cuota_sheets_excedida
from core.services import alcance_combiner
from core.services.alcance_provisional import analizar_alcance_provisional
from core.services.comparador_alcance import comparar_propuesta_vs_hoja
from core.services.hojas_ingenieria import listar_todos_cambio_nt, listar_todos_normalizaciones_indirectas
from core.services.job_store import EstadoJob
from core.services.opex_desde_equipos import construir_opex_desde_equipos
from core.services.operator_resolver import FUENTE_PENDIENTE_MANUAL, resolver_operador_red
from core.utils import normalizar_codigo

SHEET_LOTE = "PyLoteAlcance"
_COLUMNAS = [
    "lote_id", "co", "fuente", "estado", "datos_hoja_json",
    "actas_pendientes_json", "spec_combinado_json", "actas_usadas_json", "observaciones_json",
    "tiene_acta_instalacion", "capacidades_vistas_json", "relaciones_tc_vistas_json",
    "resultado_json", "comparacion_json", "opex_resultado_json", "opex_alerta", "actualizado_en",
]

ESTADO_PENDIENTE = "pendiente"
ESTADO_LEYENDO_ACTAS = "leyendo_actas"
ESTADO_COMPLETO = "completo"
ESTADO_ERROR = "error"
_ESTADOS_TERMINALES = (ESTADO_COMPLETO, ESTADO_ERROR)


@dataclass
class FilaLote:
    lote_id: str
    co: str
    fuente: str  # "cambio_nt" | "norm_indirectas"
    estado: str
    datos_hoja: dict
    job: EstadoJob
    resultado: dict | None = None
    comparacion: dict | None = None
    opex_resultado: dict | None = None
    opex_alerta: str | None = None


class LoteStore:
    def __init__(self, sheets: SheetsClient):
        self._sheets = sheets

    def _hoja(self):
        try:
            return self._sheets.hoja_por_nombre(SHEET_LOTE)
        except RuntimeError:
            hoja = self._sheets.crear_hoja(SHEET_LOTE, filas=5000, columnas=len(_COLUMNAS))
            con_reintento_sheets(hoja.append_row, _COLUMNAS)
            return hoja

    def _fila_valores(self, f: FilaLote) -> list:
        j = f.job
        return [
            f.lote_id, f.co, f.fuente, f.estado, json.dumps(f.datos_hoja, ensure_ascii=False),
            json.dumps(j.actas_pendientes, ensure_ascii=False),
            json.dumps(j.spec_combinado, ensure_ascii=False),
            json.dumps(j.actas_usadas, ensure_ascii=False),
            json.dumps(j.observaciones, ensure_ascii=False),
            "1" if j.tiene_acta_instalacion else "0",
            json.dumps(j.capacidades_vistas, ensure_ascii=False),
            json.dumps(j.relaciones_tc_vistas, ensure_ascii=False),
            json.dumps(f.resultado, ensure_ascii=False) if f.resultado is not None else "",
            json.dumps(f.comparacion, ensure_ascii=False) if f.comparacion is not None else "",
            json.dumps(f.opex_resultado, ensure_ascii=False) if f.opex_resultado is not None else "",
            f.opex_alerta or "",
            str(int(time.time())),
        ]

    def _fila_desde_valores(self, fila: list) -> FilaLote:
        fila = list(fila) + [""] * (len(_COLUMNAS) - len(fila))
        job = EstadoJob(
            co=fila[1], estado="en_progreso",
            actas_pendientes=json.loads(fila[5] or "[]"),
            spec_combinado=json.loads(fila[6] or "{}"),
            actas_usadas=json.loads(fila[7] or "[]"),
            observaciones=json.loads(fila[8] or "[]"),
            tiene_acta_instalacion=(fila[9] == "1"),
            capacidades_vistas=json.loads(fila[10] or "[]"),
            relaciones_tc_vistas=json.loads(fila[11] or "[]"),
        )
        return FilaLote(
            lote_id=fila[0], co=fila[1], fuente=fila[2], estado=fila[3],
            datos_hoja=json.loads(fila[4] or "{}"), job=job,
            resultado=json.loads(fila[12]) if fila[12] else None,
            comparacion=json.loads(fila[13]) if fila[13] else None,
            opex_resultado=json.loads(fila[14]) if fila[14] else None,
            opex_alerta=fila[15] or None,
        )

    def crear_lote(self, cos_pegados: list[str]) -> dict:
        cambio_nt = listar_todos_cambio_nt(self._sheets)
        norm_indirectas = listar_todos_normalizaciones_indirectas(self._sheets)
        lote_id = uuid.uuid4().hex[:12]

        filas_nuevas = []
        vistos: set[str] = set()
        for co_raw in cos_pegados:
            co = normalizar_codigo(co_raw)
            if not co or co in vistos:
                continue
            vistos.add(co)
            if co in cambio_nt:
                fuente, datos_hoja = "cambio_nt", cambio_nt[co]
            elif co in norm_indirectas:
                fuente, datos_hoja = "norm_indirectas", norm_indirectas[co]
            else:
                continue  # no está en ninguna de las 2 hojas — se descarta en silencio
            f = FilaLote(lote_id=lote_id, co=co, fuente=fuente, estado=ESTADO_PENDIENTE, datos_hoja=datos_hoja, job=EstadoJob(co=co, estado="pendiente"))
            filas_nuevas.append(self._fila_valores(f))

        if filas_nuevas:
            # append_rows (sin rango explícito) le pide a Sheets que "busque una tabla" para
            # decidir en qué columna insertar — con muchos lotes creados en el tiempo, cada
            # búsqueda encontraba la tabla anterior y la siguiente corrida quedaba pegada a su
            # derecha, no debajo en columna A (bug real, Dinovi 2026-09-24: filas de lotes
            # previos aparecían desplazadas ~16 columnas por cada lote nuevo creado, dejándolas
            # invisibles para _filas_del_lote). Range explícito = sin ambigüedad, igual que ya
            # hace siguiente_paso() con hoja.update(f"A{fila_idx}:...").
            hoja = self._hoja()
            fila_inicio = len(con_reintento_sheets(hoja.get_all_values)) + 1
            fila_fin = fila_inicio + len(filas_nuevas) - 1
            col_fin = chr(ord('A') + len(_COLUMNAS) - 1)
            con_reintento_sheets(hoja.update, f"A{fila_inicio}:{col_fin}{fila_fin}", filas_nuevas)
        return {"lote_id": lote_id, "total": len(filas_nuevas), "descartados": len(vistos) - len(filas_nuevas)}

    def _calcular_opex(self, f: FilaLote, llm, metabase, resultado: dict, drive_cfg=None) -> None:
        """OPEX del lote (Dinovi, 2026-09-24): "que cumpla la misma función que la primera
        pestaña, solo que masivo" — automático, sin exclusiones manuales de fila (no hay quién
        las marque en un lote de 400), es_instalacion_nueva=False (estos CO son cambios de
        equipo por Art.19, no instalaciones nuevas) y secciones = las que ya detectó el
        dictamen (igual que si nadie hubiera excluido nada en la pantalla individual)."""
        try:
            or_res = resolver_operador_red(self._sheets, metabase, llm, f.co, drive_cfg)
            if or_res.fuente == FUENTE_PENDIENTE_MANUAL:
                f.opex_alerta = or_res.motivo
                return
            diagnostico, spec, propuesta = resultado["diagnostico"], resultado["spec"], resultado["propuesta"]
            celda_sku = next((p.get("sku") for p in propuesta if (p.get("grupo") or "").strip().lower() == "celda"), None)
            filas_cable = [{"grupo": p.get("grupo"), "cantidad": p.get("cantidad", 1)} for p in propuesta if "cable" in (p.get("grupo") or "").lower()]
            opex = construir_opex_desde_equipos(
                self._sheets, f.co, or_res.or_raw, diagnostico["tipo_medida_final"], spec.get("ubicacion_medida"),
                resultado.get("secciones") or {}, False, filas_cable,
                tipo_medida_actual=diagnostico.get("tipo_medida_actual"), celda_sku=celda_sku,
            )
            f.opex_resultado = {
                "operador": opex.operador, "orOriginal": opex.or_original, "fuenteOperador": or_res.fuente,
                "filas": opex.filas, "totalGeneral": opex.total_general, "alertas": opex.alertas, "nota": opex.nota,
            }
        except Exception as e:  # noqa: BLE001 — un fallo de OPEX no debe perder el CAPEX ya calculado
            f.opex_alerta = f"No se pudo calcular OPEX: {e}"

    def _filas_del_lote(self, hoja, lote_id: str) -> list[tuple[int, list]]:
        valores = con_reintento_sheets(hoja.get_all_values)
        return [(i, fila) for i, fila in enumerate(valores[1:], start=2) if fila and fila[0] == lote_id]

    def siguiente_paso(self, llm, drive_cfg, metabase, lote_id: str) -> dict:
        if hasattr(llm, "contexto"):
            llm.contexto = {**llm.contexto, "origen": "lote"}  # para separar el consumo de los lotes en PyConsumo
        hoja = self._hoja()
        filas = self._filas_del_lote(hoja, lote_id)
        if not filas:
            return {"lote_id": lote_id, "completo_lote": True, "procesados": 0, "total": 0, "co_actual": None}

        total = len(filas)
        procesados = sum(1 for _, fila in filas if len(fila) > 3 and fila[3] in _ESTADOS_TERMINALES)
        pendiente = next(((idx, fila) for idx, fila in filas if len(fila) > 3 and fila[3] not in _ESTADOS_TERMINALES), None)
        if pendiente is None:
            return {"lote_id": lote_id, "completo_lote": True, "procesados": procesados, "total": total, "co_actual": None}

        fila_idx, valores_fila = pendiente
        f = self._fila_desde_valores(valores_fila)

        try:
            filas_metabase_co = metabase.filas_por_co(f.co)
            if f.estado == ESTADO_PENDIENTE:
                f.job.actas_pendientes = alcance_combiner.preparar_actas_pendientes(f.co, filas_metabase_co)
                f.job.tiene_acta_instalacion = alcance_combiner.hay_acta_instalacion(filas_metabase_co)
                f.estado = ESTADO_LEYENDO_ACTAS

            resultado_paso = alcance_combiner.procesar_siguiente_acta(f.job, llm, drive_cfg, self._sheets, permitir_modo_imagen=True)
            f.job = resultado_paso.estado

            if resultado_paso.completo:
                acta_resultado = alcance_combiner.acta_resultado_desde_estado(f.job)
                dictamen = {"clasificacion": "normalizacion"}
                resultado = analizar_alcance_provisional(self._sheets, llm, f.co, dictamen, acta_resultado, filas_metabase_co)
                f.resultado = resultado
                f.comparacion = comparar_propuesta_vs_hoja(resultado["propuesta"], f.datos_hoja, f.fuente)
                self._calcular_opex(f, llm, metabase, resultado, drive_cfg)
                f.estado = ESTADO_COMPLETO
                procesados += 1
        except Exception as e:  # noqa: BLE001 — un CO con error no debe tumbar el resto del lote
            if es_cuota_sheets_excedida(e):
                # 429 transitorio de Sheets (Dinovi, 2026-09-28: CO0500000755 quedó marcado
                # como error permanente por esto) — NO es un error real de este CO, es una
                # ráfaga sostenida que ya agotó los reintentos de con_reintento_sheets. Se deja
                # el estado como estaba (con el progreso ya hecho, si alguno) para que el
                # PRÓXIMO paso del lote lo vuelva a intentar, en vez de darlo por perdido.
                f.job.observaciones.append(f"Cuota de Sheets agotada momentáneamente, se reintentará en el próximo paso: {e}")
            else:
                f.estado = ESTADO_ERROR
                f.job.observaciones.append(f"Error procesando este CO: {e}")
                procesados += 1

        con_reintento_sheets(hoja.update, f"A{fila_idx}:{chr(ord('A') + len(_COLUMNAS) - 1)}{fila_idx}", [self._fila_valores(f)])
        return {
            "lote_id": lote_id, "completo_lote": procesados >= total, "procesados": procesados,
            "total": total, "co_actual": f.co, "estado_co": f.estado,
        }

    def leer_lote(self, lote_id: str) -> list[dict]:
        hoja = self._hoja()
        filas = self._filas_del_lote(hoja, lote_id)
        resultado = []
        for _, valores_fila in filas:
            f = self._fila_desde_valores(valores_fila)
            resultado.append({
                "co": f.co, "fuente": f.fuente, "estado": f.estado,
                "resultado": f.resultado, "comparacion": f.comparacion,
                "opex": f.opex_resultado, "opexAlerta": f.opex_alerta,
                "observaciones": f.job.observaciones,
            })
        return resultado


def get_lote_store(sheets: SheetsClient) -> LoteStore:
    return LoteStore(sheets)
