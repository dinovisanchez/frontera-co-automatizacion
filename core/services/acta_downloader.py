"""Descarga y valida el PDF de una acta desde act_pdf_url — puerto de descargarPdfActa /
extraerPdfDeZip (Codigo.gs líneas 3344-3379).

Soporta .pdf directo y .zip (se descomprime buscando el primer .pdf adentro); .rar/.7z se
rechazan explícitamente igual que en el original (sin soporte de descompresión).
"""

import io
import zipfile
from dataclasses import dataclass

import requests

# Codigo.gs (LIMITE_BYTES_DESCARGA, línea 3249) usaba 20MB, limitado por Apps Script — en
# Vercel (maxDuration 60s, sin el límite de tiempo de ejecución de Apps Script) hay margen
# real para más. Subido a 50MB (Dinovi, 2026-09-23, CO0800000348: una acta INFR real de 42MB
# se estaba descartando sin necesidad — 344MB en cambio SÍ sigue siendo inviable, ver
# CO0100000215, no hay evidencia de que valga la pena subir esto mucho más).
LIMITE_BYTES_DESCARGA = 50 * 1024 * 1024

# Umbral para decidir si vale la pena el modo "con imágenes" (PDF completo en base64) como
# fallback cuando el modo texto no trajo todo — Codigo.gs línea 3250.
LIMITE_BYTES_MODO_IMAGEN = 10 * 1024 * 1024

_EXTENSIONES_NO_SOPORTADAS = {"rar", "7z"}


@dataclass
class ResultadoDescarga:
    ok: bool
    bytes_pdf: bytes | None = None
    motivo_fallo: str | None = None  # se registra en "intentos" por el llamador


def _extension_de_url(url: str) -> str:
    return url.split("?")[0].rsplit(".", 1)[-1].lower() if "." in url.split("?")[0] else ""


def _extraer_pdf_de_zip(zip_bytes: bytes) -> ResultadoDescarga:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            nombres_pdf = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
            if not nombres_pdf:
                return ResultadoDescarga(
                    ok=False,
                    motivo_fallo=f".zip sin ningún PDF adentro ({len(zf.namelist())} archivo(s): {', '.join(zf.namelist())})",
                )
            return ResultadoDescarga(ok=True, bytes_pdf=zf.read(nombres_pdf[0]))
    except zipfile.BadZipFile as e:
        return ResultadoDescarga(ok=False, motivo_fallo=f"no se pudo descomprimir el .zip — {e}")


def descargar_pdf_acta(url: str) -> ResultadoDescarga:
    """Puerto de descargarPdfActa(url, etiqueta) — el `motivo_fallo` reemplaza el `intentos.push(...)`
    del original; el llamador (alcance_combiner) decide cómo registrarlo.
    """
    extension = _extension_de_url(url)
    if extension in _EXTENSIONES_NO_SOPORTADAS:
        return ResultadoDescarga(ok=False, motivo_fallo=f"es .{extension}, no se puede descomprimir (solo .zip soportado)")

    try:
        resp = requests.get(url, timeout=120)
    except requests.RequestException as e:
        return ResultadoDescarga(ok=False, motivo_fallo=str(e))

    if resp.status_code != 200:
        return ResultadoDescarga(ok=False, motivo_fallo=f"HTTP {resp.status_code}")

    contenido = resp.content
    if len(contenido) >= LIMITE_BYTES_DESCARGA:
        return ResultadoDescarga(ok=False, motivo_fallo=f"{round(len(contenido) / 1024 / 1024)}MB, muy grande incluso para OCR")

    if extension == "zip":
        resultado_zip = _extraer_pdf_de_zip(contenido)
        if not resultado_zip.ok:
            return resultado_zip
        contenido = resultado_zip.bytes_pdf
        if len(contenido) >= LIMITE_BYTES_DESCARGA:
            return ResultadoDescarga(ok=False, motivo_fallo="el PDF dentro del .zip también es muy grande")

    if contenido[:4] != b"%PDF":
        return ResultadoDescarga(ok=False, motivo_fallo="no es un PDF válido")

    return ResultadoDescarga(ok=True, bytes_pdf=contenido)
