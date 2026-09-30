"""Lectura/escritura en Google Sheets vía cuenta de servicio — reemplaza SpreadsheetApp.

Equivale a los ss.getSheetByName(...)/hoja.getRange(...).getValues() de Codigo.gs. Usa
gspread + credenciales de cuenta de servicio (JSON completo en la variable de entorno
GOOGLE_SERVICE_ACCOUNT_JSON), nunca un archivo de credenciales en el repo.
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import gspread
from google.oauth2.service_account import Credentials

from config.settings import GoogleSheetsConfig

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_TTL_HOJA_SEG = 300  # mismo TTL que MetabaseClient — el nombre/gid de una hoja no cambia seguido.
_MAX_REINTENTOS_429 = 4
_BACKOFF_BASE_SEG = 2.0

_T = TypeVar("_T")


def _es_429(e: gspread.exceptions.APIError) -> bool:
    return getattr(e, "code", None) == 429 or (e.response is not None and e.response.status_code == 429)


def es_cuota_sheets_excedida(e: Exception) -> bool:
    """Para que un llamador (ej. lote_store.siguiente_paso) distinga un 429 de Sheets — que ya
    sobrevivió los reintentos de con_reintento_sheets y sigue fallando por una ráfaga sostenida
    — de un error real del CO: el primero se debe reintentar en un paso futuro, no marcar el
    CO como error permanente (Dinovi, 2026-09-28)."""
    return isinstance(e, gspread.exceptions.APIError) and _es_429(e)


def con_reintento_sheets(fn: Callable[..., _T], *args, **kwargs) -> _T:
    """Google Sheets tiene cuota de "lecturas/minuto por usuario" — un lote de cientos de CO
    (Comparación Masiva) puede agotarla en ráfaga (Dinovi, 2026-09-25: HTTP 500 real en
    producción por APIError 429 de Sheets, tumbando /api/lote_step sin reintento). Reintenta
    con backoff solo en 429; cualquier otro error de Sheets se propaga igual que antes."""
    ultimo: gspread.exceptions.APIError | None = None
    for intento in range(1, _MAX_REINTENTOS_429 + 1):
        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            if not _es_429(e) or intento == _MAX_REINTENTOS_429:
                raise
            ultimo = e
            time.sleep(_BACKOFF_BASE_SEG * (2 ** (intento - 1)))
    raise ultimo  # pragma: no cover — inalcanzable, el loop siempre retorna o lanza antes


@dataclass
class _HojaCacheEntry:
    hoja: "gspread.Worksheet"
    expira_en: float


# Caché a nivel de MÓDULO (mismo patrón que MetabaseClient) — gspread NO cachea nada de esto:
# Spreadsheet.worksheet()/worksheets() llaman fetch_sheet_metadata() (una lectura de la API)
# CADA VEZ que se piden, y construir_dependencias() crea un SheetsClient nuevo en cada
# invocación de Vercel. Con ~10 hojas distintas consultadas por paso del lote, esto es la causa
# real del 429 de cuota — cachear la conexión y los Worksheet ya resueltos entre invocaciones
# del mismo contenedor tibio corta la enorme mayoría de esas lecturas repetidas.
_gc_global: gspread.Client | None = None
_spreadsheets_global: dict[str, gspread.Spreadsheet] = {}
_hojas_global: dict[tuple, _HojaCacheEntry] = {}


class SheetsClient:
    """Wrapper delgado sobre gspread para una única hoja de cálculo (ALCANCE_SHEET_ID)."""

    def __init__(self, cfg: GoogleSheetsConfig):
        global _gc_global
        self._alcance_sheet_id = cfg.alcance_sheet_id
        if _gc_global is None:
            info = json.loads(cfg.service_account_json)
            creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
            _gc_global = gspread.authorize(creds)
        self._gc = _gc_global
        self._spreadsheet = self._abrir_spreadsheet(cfg.alcance_sheet_id)

    def _abrir_spreadsheet(self, spreadsheet_id: str) -> gspread.Spreadsheet:
        if spreadsheet_id not in _spreadsheets_global:
            _spreadsheets_global[spreadsheet_id] = con_reintento_sheets(self._gc.open_by_key, spreadsheet_id)
        return _spreadsheets_global[spreadsheet_id]

    def _hoja_cacheada(self, clave: tuple, resolver: Callable[[], gspread.Worksheet]) -> gspread.Worksheet:
        ahora = time.monotonic()
        entrada = _hojas_global.get(clave)
        if entrada and entrada.expira_en > ahora:
            return entrada.hoja
        hoja = resolver()
        _hojas_global[clave] = _HojaCacheEntry(hoja=hoja, expira_en=ahora + _TTL_HOJA_SEG)
        return hoja

    def hoja_por_nombre(self, nombre: str) -> gspread.Worksheet:
        clave = (self._alcance_sheet_id, "nombre", nombre)
        try:
            return self._hoja_cacheada(clave, lambda: con_reintento_sheets(self._spreadsheet.worksheet, nombre))
        except gspread.WorksheetNotFound as e:
            raise RuntimeError(f'No encontré la hoja "{nombre}".') from e

    def crear_hoja(self, nombre: str, filas: int, columnas: int) -> gspread.Worksheet:
        hoja = con_reintento_sheets(self._spreadsheet.add_worksheet, title=nombre, rows=filas, cols=columnas)
        _hojas_global[(self._alcance_sheet_id, "nombre", nombre)] = _HojaCacheEntry(hoja=hoja, expira_en=time.monotonic() + _TTL_HOJA_SEG)
        return hoja

    def hoja_por_gid(self, gid: int) -> gspread.Worksheet:
        clave = (self._alcance_sheet_id, "gid", gid)

        def resolver() -> gspread.Worksheet:
            for hoja in con_reintento_sheets(self._spreadsheet.worksheets):
                if hoja.id == gid:
                    return hoja
            raise RuntimeError(f"No encontré ninguna hoja con gid {gid} en la hoja de Alcances.")

        return self._hoja_cacheada(clave, resolver)

    def hoja_externa_por_gid(self, spreadsheet_id: str, gid: int) -> gspread.Worksheet | None:
        """Como hoja_por_gid, pero en OTRA hoja de cálculo (ej. "Data cambio NT", la hoja
        maestra) — la misma cuenta de servicio debe tener acceso de lectura compartido ahí.
        Devuelve None (no lanza) si la hoja no existe o no está compartida — igual que
        obtenerHojaAlcancePorGid en Codigo.gs, para no tumbar el resto del análisis.
        """
        clave = (spreadsheet_id, "gid", gid)
        ahora = time.monotonic()
        entrada = _hojas_global.get(clave)
        if entrada and entrada.expira_en > ahora:
            return entrada.hoja
        try:
            if spreadsheet_id not in _spreadsheets_global:
                _spreadsheets_global[spreadsheet_id] = con_reintento_sheets(self._gc.open_by_key, spreadsheet_id)
            spreadsheet = _spreadsheets_global[spreadsheet_id]
            for hoja in con_reintento_sheets(spreadsheet.worksheets):
                if hoja.id == gid:
                    _hojas_global[clave] = _HojaCacheEntry(hoja=hoja, expira_en=ahora + _TTL_HOJA_SEG)
                    return hoja
        except (gspread.SpreadsheetNotFound, gspread.exceptions.APIError):
            # No existe, o la cuenta de servicio no tiene acceso compartido ahí — no debe
            # tumbar el resto del análisis (igual que el try/catch del original).
            return None
        return None

    def copiar_fila(
        self, hoja: gspread.Worksheet, fila_origen: int, fila_destino: int, num_columnas: int, col_inicio: int = 0
    ) -> None:
        """Copia una fila completa (fórmulas, formato, validación de datos) a otra fila del
        MISMO documento — equivalente a Range.copyTo() de Apps Script (usado por
        guardarAlcanceProvisional para heredar las fórmulas de costo de las columnas H/I de
        "Equipos" en la fila nueva). gspread no expone esto como helper, así que se manda el
        request crudo de la Sheets API; las referencias relativas de una fórmula (ej.
        VLOOKUP(E5,...)) se ajustan solas a la fila destino, igual que copyTo().

        Copia las columnas [col_inicio, num_columnas) (0-indexado, fin exclusivo) — por defecto
        desde la A; con `col_inicio` se puede copiar UNA sola columna (ej. H = 7 a 8).
        """
        body = {
            "requests": [{
                "copyPaste": {
                    "source": {
                        "sheetId": hoja.id,
                        "startRowIndex": fila_origen - 1, "endRowIndex": fila_origen,
                        "startColumnIndex": col_inicio, "endColumnIndex": num_columnas,
                    },
                    "destination": {
                        "sheetId": hoja.id,
                        "startRowIndex": fila_destino - 1, "endRowIndex": fila_destino,
                        "startColumnIndex": col_inicio, "endColumnIndex": num_columnas,
                    },
                    "pasteType": "PASTE_NORMAL",
                }
            }]
        }
        con_reintento_sheets(self._spreadsheet.batch_update, body)

    def leer_todo(self, hoja: gspread.Worksheet, sin_formato: bool = False) -> list[list[Any]]:
        """Equivalente a hoja.getRange(1,1,ultimaFila,ultimaColumna).getValues().

        `sin_formato=True` pide UNFORMATTED_VALUE (números crudos, ej. 118750.0) en vez del
        texto tal como se ve en pantalla (ej. "$118,750.00") — getValues() de Apps Script
        SIEMPRE devuelve el valor crudo, así que cualquier hoja con columnas numéricas
        formateadas (moneda, %, fecha) necesita esto para no romper un float()/int() más abajo.
        """
        opcion = "UNFORMATTED_VALUE" if sin_formato else "FORMATTED_VALUE"
        return con_reintento_sheets(hoja.get_values, value_render_option=opcion)

    def leer_rango(
        self, hoja: gspread.Worksheet, fila_inicio: int, col_inicio: int, num_filas: int, num_cols: int, sin_formato: bool = False
    ) -> list[list[Any]]:
        """1-indexado, igual que Range de Apps Script. Ver `leer_todo` sobre `sin_formato`."""
        fila_fin = fila_inicio + num_filas - 1
        col_fin = col_inicio + num_cols - 1
        rango = gspread.utils.rowcol_to_a1(fila_inicio, col_inicio) + ":" + gspread.utils.rowcol_to_a1(
            fila_fin, col_fin
        )
        opcion = "UNFORMATTED_VALUE" if sin_formato else "FORMATTED_VALUE"
        valores = con_reintento_sheets(hoja.get, rango, value_render_option=opcion)
        # gspread recorta filas/columnas vacías al final — se rellena para conservar la forma
        # esperada por el código que porta la lógica de Codigo.gs (acceso por índice fijo).
        for fila in valores:
            while len(fila) < num_cols:
                fila.append("")
        while len(valores) < num_filas:
            valores.append([""] * num_cols)
        return valores
