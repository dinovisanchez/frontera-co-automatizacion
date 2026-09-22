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

    def leer_todo(self, hoja: gspread.Worksheet) -> list[list[Any]]:
        """Equivalente a hoja.getRange(1,1,ultimaFila,ultimaColumna).getValues()."""
        return hoja.get_all_values()

    def leer_rango(
        self, hoja: gspread.Worksheet, fila_inicio: int, col_inicio: int, num_filas: int, num_cols: int
    ) -> list[list[Any]]:
        """1-indexado, igual que Range de Apps Script."""
        fila_fin = fila_inicio + num_filas - 1
        col_fin = col_inicio + num_cols - 1
        rango = gspread.utils.rowcol_to_a1(fila_inicio, col_inicio) + ":" + gspread.utils.rowcol_to_a1(
            fila_fin, col_fin
        )
        valores = hoja.get(rango)
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
