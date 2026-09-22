"""Lectura/escritura en Google Sheets vía cuenta de servicio — reemplaza SpreadsheetApp.

Equivale a los ss.getSheetByName(...)/hoja.getRange(...).getValues() de Codigo.gs. Usa
gspread + credenciales de cuenta de servicio (JSON completo en la variable de entorno
GOOGLE_SERVICE_ACCOUNT_JSON), nunca un archivo de credenciales en el repo.
"""

import json
from functools import lru_cache
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from config.settings import GoogleSheetsConfig

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class SheetsClient:
    """Wrapper delgado sobre gspread para una única hoja de cálculo (ALCANCE_SHEET_ID)."""

    def __init__(self, cfg: GoogleSheetsConfig):
        info = json.loads(cfg.service_account_json)
        creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
        self._gc = gspread.authorize(creds)
        self._spreadsheet = self._gc.open_by_key(cfg.alcance_sheet_id)
        self._otras_hojas_cache: dict[str, gspread.Spreadsheet] = {}

    def hoja_por_nombre(self, nombre: str) -> gspread.Worksheet:
        try:
            return self._spreadsheet.worksheet(nombre)
        except gspread.WorksheetNotFound as e:
            raise RuntimeError(f'No encontré la hoja "{nombre}".') from e

    def crear_hoja(self, nombre: str, filas: int, columnas: int) -> gspread.Worksheet:
        return self._spreadsheet.add_worksheet(title=nombre, rows=filas, cols=columnas)

    def hoja_por_gid(self, gid: int) -> gspread.Worksheet:
        for hoja in self._spreadsheet.worksheets():
            if hoja.id == gid:
                return hoja
        raise RuntimeError(f"No encontré ninguna hoja con gid {gid} en la hoja de Alcances.")

    def hoja_externa_por_gid(self, spreadsheet_id: str, gid: int) -> gspread.Worksheet | None:
        """Como hoja_por_gid, pero en OTRA hoja de cálculo (ej. "Data cambio NT", la hoja
        maestra) — la misma cuenta de servicio debe tener acceso de lectura compartido ahí.
        Devuelve None (no lanza) si la hoja no existe o no está compartida — igual que
        obtenerHojaAlcancePorGid en Codigo.gs, para no tumbar el resto del análisis.
        """
        if spreadsheet_id not in self._otras_hojas_cache:
            try:
                self._otras_hojas_cache[spreadsheet_id] = self._gc.open_by_key(spreadsheet_id)
            except (gspread.SpreadsheetNotFound, gspread.exceptions.APIError):
                # No existe, o la cuenta de servicio no tiene acceso compartido ahí — no debe
                # tumbar el resto del análisis (igual que el try/catch del original).
                return None
        spreadsheet = self._otras_hojas_cache[spreadsheet_id]
        for hoja in spreadsheet.worksheets():
            if hoja.id == gid:
                return hoja
        return None

    def copiar_fila(self, hoja: gspread.Worksheet, fila_origen: int, fila_destino: int, num_columnas: int) -> None:
        """Copia una fila completa (fórmulas, formato, validación de datos) a otra fila del
        MISMO documento — equivalente a Range.copyTo() de Apps Script (usado por
        guardarAlcanceProvisional para heredar las fórmulas de costo de las columnas H/I de
        "Equipos" en la fila nueva). gspread no expone esto como helper, así que se manda el
        request crudo de la Sheets API; las referencias relativas de una fórmula (ej.
        VLOOKUP(E5,...)) se ajustan solas a la fila destino, igual que copyTo().
        """
        body = {
            "requests": [{
                "copyPaste": {
                    "source": {
                        "sheetId": hoja.id,
                        "startRowIndex": fila_origen - 1, "endRowIndex": fila_origen,
                        "startColumnIndex": 0, "endColumnIndex": num_columnas,
                    },
                    "destination": {
                        "sheetId": hoja.id,
                        "startRowIndex": fila_destino - 1, "endRowIndex": fila_destino,
                        "startColumnIndex": 0, "endColumnIndex": num_columnas,
                    },
                    "pasteType": "PASTE_NORMAL",
                }
            }]
        }
        self._spreadsheet.batch_update(body)

    def leer_todo(self, hoja: gspread.Worksheet, sin_formato: bool = False) -> list[list[Any]]:
        """Equivalente a hoja.getRange(1,1,ultimaFila,ultimaColumna).getValues().

        `sin_formato=True` pide UNFORMATTED_VALUE (números crudos, ej. 118750.0) en vez del
        texto tal como se ve en pantalla (ej. "$118,750.00") — getValues() de Apps Script
        SIEMPRE devuelve el valor crudo, así que cualquier hoja con columnas numéricas
        formateadas (moneda, %, fecha) necesita esto para no romper un float()/int() más abajo.
        """
        opcion = "UNFORMATTED_VALUE" if sin_formato else "FORMATTED_VALUE"
        return hoja.get_values(value_render_option=opcion)

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
        valores = hoja.get(rango, value_render_option=opcion)
        # gspread recorta filas/columnas vacías al final — se rellena para conservar la forma
        # esperada por el código que porta la lógica de Codigo.gs (acceso por índice fijo).
        for fila in valores:
            while len(fila) < num_cols:
                fila.append("")
        while len(valores) < num_filas:
            valores.append([""] * num_cols)
        return valores


@lru_cache(maxsize=1)
def get_sheets_client() -> SheetsClient:
    from config.settings import cargar_sheets_config

    return SheetsClient(cargar_sheets_config())
