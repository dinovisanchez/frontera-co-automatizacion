"""Estado intermedio del análisis de un CO — permite reanudar entre invocaciones serverless.

Justificación (ver README, sección "Por qué una acta por invocación"): el tiempo de cada
acta es impredecible (texto vs. imagen, hasta 20MB) — Codigo.gs ya lo documentaba como riesgo
de timeout incluso con los 30 min de Apps Script (línea 3252-3259). Un endpoint de Vercel NO
puede asumir que le va a alcanzar el tiempo para todas las actas de un CO de una sola vez, así
que cada invocación procesa UNA acta y guarda el progreso acá para que la siguiente invocación
continúe donde quedó — mismo principio que la hoja "AsyncJobs" que Codigo.gs ya usaba para su
propio patrón de job asíncrono (línea 2427).

Se persiste en una pestaña de Google Sheets (no en el filesystem de la función, que no
sobrevive entre invocaciones, ni en memoria del proceso, que Vercel puede reciclar en
cualquier momento).
"""

import json
import time
from dataclasses import dataclass, field

from core.data_sources.sheets_client import SheetsClient

SHEET_JOBS = "PyAsyncJobs"
_COLUMNAS = ["co", "estado", "actas_pendientes_json", "spec_combinado_json", "actas_usadas_json", "observaciones_json", "actualizado_en"]

ESTADO_PENDIENTE = "pendiente"
ESTADO_EN_PROGRESO = "en_progreso"
ESTADO_COMPLETO = "completo"
ESTADO_ERROR = "error"


@dataclass
class EstadoJob:
    co: str
    estado: str
    actas_pendientes: list[dict] = field(default_factory=list)
    spec_combinado: dict = field(default_factory=dict)
    actas_usadas: list[dict] = field(default_factory=list)
    observaciones: list[str] = field(default_factory=list)


class JobStore:
    def __init__(self, sheets: SheetsClient):
        self._sheets = sheets

    def _hoja(self):
        try:
            return self._sheets.hoja_por_nombre(SHEET_JOBS)
        except RuntimeError:
            hoja = self._sheets.crear_hoja(SHEET_JOBS, filas=1000, columnas=len(_COLUMNAS))
            hoja.append_row(_COLUMNAS)
            return hoja

    def _fila_de(self, hoja, co: str) -> int | None:
        valores = hoja.get_all_values()
        for i, fila in enumerate(valores[1:], start=2):
            if fila and fila[0] == co:
                return i
        return None

    def crear_o_reiniciar(self, co: str, actas_pendientes: list[dict]) -> EstadoJob:
        estado = EstadoJob(co=co, estado=ESTADO_EN_PROGRESO, actas_pendientes=actas_pendientes)
        self._guardar(estado)
        return estado

    def leer(self, co: str) -> EstadoJob | None:
        hoja = self._hoja()
        fila_idx = self._fila_de(hoja, co)
        if fila_idx is None:
            return None
        fila = hoja.row_values(fila_idx)
        fila += [""] * (len(_COLUMNAS) - len(fila))
        return EstadoJob(
            co=fila[0],
            estado=fila[1],
            actas_pendientes=json.loads(fila[2] or "[]"),
            spec_combinado=json.loads(fila[3] or "{}"),
            actas_usadas=json.loads(fila[4] or "[]"),
            observaciones=json.loads(fila[5] or "[]"),
        )

    def _guardar(self, estado: EstadoJob) -> None:
        hoja = self._hoja()
        fila_valores = [
            estado.co,
            estado.estado,
            json.dumps(estado.actas_pendientes, ensure_ascii=False),
            json.dumps(estado.spec_combinado, ensure_ascii=False),
            json.dumps(estado.actas_usadas, ensure_ascii=False),
            json.dumps(estado.observaciones, ensure_ascii=False),
            str(int(time.time())),
        ]
        fila_idx = self._fila_de(hoja, estado.co)
        if fila_idx is None:
            hoja.append_row(fila_valores)
        else:
            hoja.update(f"A{fila_idx}:G{fila_idx}", [fila_valores])

    def guardar_progreso(self, estado: EstadoJob) -> None:
        self._guardar(estado)

    def marcar_completo(self, estado: EstadoJob) -> None:
        estado.estado = ESTADO_COMPLETO
        self._guardar(estado)

    def marcar_error(self, estado: EstadoJob, mensaje: str) -> None:
        estado.estado = ESTADO_ERROR
        estado.observaciones.append(mensaje)
        self._guardar(estado)

    def listar_cos_por_estado(self, estado: str) -> list[str]:
        """Usado por cron_reintentos.py para encontrar jobs que quedaron a medias (ej. el
        frontend se desconectó antes de terminar de hacer polling)."""
        hoja = self._hoja()
        valores = hoja.get_all_values()
        return [fila[0] for fila in valores[1:] if len(fila) > 1 and fila[1] == estado]


def get_job_store(sheets: SheetsClient) -> JobStore:
    return JobStore(sheets)
