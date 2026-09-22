"""OCR de texto de un PDF de acta — puerto de ocrTextoDesdeBytes (Codigo.gs línea 1009).

El original usa el truco de Apps Script: sube el PDF a Drive pidiendo conversión a Google
Docs con `ocr:true, ocrLanguage:'es'`, lee el texto con DocumentApp y borra el archivo
temporal. Fuera de Apps Script se logra el mismo resultado con la API de Drive v3 sola
(sin API de Docs aparte): subir con mimeType destino "application/vnd.google-apps.document"
+ ocrLanguage, exportar como text/plain, y borrar el temporal — mismo efecto neto.

Nunca lanza: devuelve OcrResultado(ok=False, ...) en vez de propagar la excepción, igual
que el original, para que el llamador pueda seguir probando otras actas.
"""

import io
import json
from dataclasses import dataclass

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from config.settings import GoogleSheetsConfig

_SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive"]
_MIN_CARACTERES_UTILES = 200  # igual que el original: menos que esto = "escaneo de mala calidad"


@dataclass
class OcrResultado:
    ok: bool
    texto: str | None = None
    motivo_fallo: str | None = None


def _cliente_drive(cfg: GoogleSheetsConfig):
    info = json.loads(cfg.service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES_DRIVE)
    return build("drive", "v3", credentials=creds)


def ocr_texto_desde_bytes(pdf_bytes: bytes, cfg: GoogleSheetsConfig) -> OcrResultado:
    drive = _cliente_drive(cfg)
    archivo_id = None
    try:
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf", resumable=False)
        metadata = {"name": "acta_ocr_temporal.pdf", "mimeType": "application/vnd.google-apps.document"}
        creado = (
            drive.files()
            .create(body=metadata, media_body=media, ocrLanguage="es", fields="id")
            .execute()
        )
        archivo_id = creado["id"]

        buffer = io.BytesIO()
        descarga = MediaIoBaseDownload(buffer, drive.files().export_media(fileId=archivo_id, mimeType="text/plain"))
        listo = False
        while not listo:
            _, listo = descarga.next_chunk()
        texto = buffer.getvalue().decode("utf-8", errors="ignore")

        if not texto or len(texto.strip()) < _MIN_CARACTERES_UTILES:
            return OcrResultado(
                ok=False,
                motivo_fallo="el OCR no extrajo suficiente texto legible (escaneo de mala calidad, o el dato clave está en una foto/diagrama)",
            )
        return OcrResultado(ok=True, texto=texto)
    except Exception as e:  # noqa: BLE001 — el original también captura cualquier error del OCR sin propagarlo
        return OcrResultado(ok=False, motivo_fallo=f"el OCR de Drive falló: {e}")
    finally:
        if archivo_id:
            try:
                drive.files().delete(fileId=archivo_id).execute()
            except Exception:  # noqa: BLE001 — limpieza best-effort, igual que el original
                pass
