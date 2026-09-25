"""Caché del resultado de extracción de UNA acta, por `act_pdf_url` — evita repetir
descarga + OCR + llamada al LLM cuando la MISMA acta se vuelve a leer: reanalizar un CO desde
cero (Dinovi, 2026-09-23: quiere que reanalizar no sea tan lento/caro), un CO que comparte una
acta con otro (una visita puede cubrir varios equipos/CO), o un reintento tras timeout.

El contenido de una acta no cambia porque se reanalice el CO, así que el caché es válido
indefinidamente (no expira) — igual que "PyAsyncJobs" (job_store.py), se persiste en una
pestaña de Google Sheets para sobrevivir entre invocaciones serverless. Solo se cachean
extracciones EXITOSAS (con al menos un campo no nulo): una acta que falló por descarga/OCR
(ej. un PDF de 344MB, ver acta_downloader.LIMITE_BYTES_DESCARGA) se reintenta en cada corrida
por si la causa era transitoria, en vez de quedar marcada como fallida para siempre.
"""

import json
import time

from core.data_sources.sheets_client import SheetsClient

SHEET_ACTAS_CACHE = "PyActasCache"
_COLUMNAS = ["url", "spec_json", "procesado_en"]


class ActaCache:
    def __init__(self, sheets: SheetsClient):
        self._sheets = sheets

    def _hoja(self):
        try:
            return self._sheets.hoja_por_nombre(SHEET_ACTAS_CACHE)
        except RuntimeError:
            hoja = self._sheets.crear_hoja(SHEET_ACTAS_CACHE, filas=2000, columnas=len(_COLUMNAS))
            hoja.append_row(_COLUMNAS)
            return hoja

    def _fila_de(self, hoja, url: str) -> int | None:
        valores = hoja.get_all_values()
        for i, fila in enumerate(valores[1:], start=2):
            if fila and fila[0] == url:
                return i
        return None

    def obtener(self, url: str) -> dict | None:
        hoja = self._hoja()
        fila_idx = self._fila_de(hoja, url)
        if fila_idx is None:
            return None
        fila = hoja.row_values(fila_idx)
        if len(fila) < 2 or not fila[1]:
            return None
        return json.loads(fila[1])

    def guardar(self, url: str, spec: dict) -> None:
        hoja = self._hoja()
        fila_valores = [url, json.dumps(spec, ensure_ascii=False), str(int(time.time()))]
        fila_idx = self._fila_de(hoja, url)
        if fila_idx is None:
            # Rango explícito, no append_row: sin rango, Sheets "busca una tabla" para decidir
            # en qué columna insertar, y esa búsqueda puede desviarse (ver el mismo bug real
            # encontrado y corregido en lote_store.crear_lote, Dinovi 2026-09-24).
            fila_nueva = len(hoja.get_all_values()) + 1
            hoja.update(f"A{fila_nueva}:C{fila_nueva}", [fila_valores])
        else:
            hoja.update(f"A{fila_idx}:C{fila_idx}", [fila_valores])


def get_acta_cache(sheets: SheetsClient) -> ActaCache:
    return ActaCache(sheets)
