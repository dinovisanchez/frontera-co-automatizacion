"""CAPEX — combina los campos de varias actas de una frontera. Puerto de
analizarActaParaAlcance (Codigo.gs líneas 3207-3600), MENOS la parte de descarga/OCR/llamada
al LLM (eso vive en acta_downloader.py / acta_ocr.py / acta_analyzer.py) y MENOS el
presupuesto de tiempo interno de 25 min: acá cada invocación procesa UNA sola acta (ver
job_store.py), así que el riesgo de timeout que ese presupuesto mitigaba en Apps Script
(línea 3252-3259) ya no existe por diseño.

Una sola acta rara vez trae todo — este módulo decide CUÁNDO ya hay suficiente para dejar
de escanear más actas, nunca inventa un valor que ninguna acta trajo.
"""

from dataclasses import dataclass

from core.data_sources.llm_client import AnthropicClient
from core.prompts.acta_extraction_prompt import CAMPOS_A_COMBINAR_ALCANCE, TIPOS_ACTA_ALCANCE
from core.services import acta_downloader, acta_ocr
from core.services.acta_analyzer import MetadatosActa, analizar_acta_desde_pdf, analizar_acta_desde_texto
from core.services.job_store import EstadoJob
from core.utils import normalizar_codigo

MAX_ACTAS_A_ESCANEAR = 5  # Codigo.gs línea 3251 — límite de costo/tiempo, no de corrección
# "Bono": se toman si alguna acta los trae, pero no detienen el escaneo por sí solos.
_CAMPOS_BONO = ("relacion_tc", "relacion_tp", "montaje_tc", "totalizador_amperios", "conductor_calibre")


@dataclass
class ResultadoPaso:
    completo: bool
    estado: EstadoJob


def preparar_actas_pendientes(co: str, filas_metabase_co: list[dict]) -> list[dict]:
    """Puerto de la deduplicación por act_pdf_url + orden por fecha desc (Codigo.gs
    líneas 3214-3237): una URL de acta puede repetirse una vez por equipo de esa visita.
    """
    filas = [
        r for r in filas_metabase_co
        if (r.get("service_type_id") or "").upper() in TIPOS_ACTA_ALCANCE and r.get("act_pdf_url")
    ]
    por_url: dict[str, dict] = {}
    for r in filas:
        url = r["act_pdf_url"]
        if url not in por_url or (r.get("fecha_visita") or "") > (por_url[url].get("fecha_visita") or ""):
            por_url[url] = r

    ordenadas = sorted(por_url.values(), key=lambda r: r.get("fecha_visita") or "", reverse=True)
    return ordenadas[:MAX_ACTAS_A_ESCANEAR]


def _faltan_campos(spec_combinado: dict) -> bool:
    if any(spec_combinado.get(c) is None for c in CAMPOS_A_COMBINAR_ALCANCE):
        return True
    if spec_combinado.get("tipo_medida_actual") != "directa" and spec_combinado.get("relacion_tc") is None:
        return True
    return False


def _combinar_en(estado: EstadoJob, fila: dict, etiqueta: str, spec: dict) -> None:
    aportados = []
    for c in CAMPOS_A_COMBINAR_ALCANCE:
        if estado.spec_combinado.get(c) is None and spec.get(c) is not None:
            estado.spec_combinado[c] = spec[c]
            aportados.append(c)
    if estado.spec_combinado.get("recuperable_por_cable") is None and spec.get("recuperable_por_cable") is not None:
        estado.spec_combinado["recuperable_por_cable"] = spec["recuperable_por_cable"]
    for c in _CAMPOS_BONO:
        if estado.spec_combinado.get(c) is None and spec.get(c) is not None:
            estado.spec_combinado[c] = spec[c]
            aportados.append(c)
    if spec.get("observaciones"):
        estado.observaciones.append(f"[{etiqueta}] {spec['observaciones']}")

    estado.actas_usadas.append({
        "url": fila["act_pdf_url"], "tipo": fila.get("service_type_id"),
        "fecha": fila.get("fecha_visita"), "aporte": aportados,
    })


def procesar_siguiente_acta(
    estado: EstadoJob, llm: AnthropicClient, drive_cfg
) -> ResultadoPaso:
    """Procesa UNA acta de estado.actas_pendientes (la más reciente primero) y actualiza
    estado.spec_combinado in-place. Devuelve completo=True cuando ya no hace falta seguir
    (todos los CAMPOS_A_COMBINAR_ALCANCE + relacion_tc si aplica, o ya no quedan actas).
    """
    if not estado.actas_pendientes or not _faltan_campos(estado.spec_combinado):
        return ResultadoPaso(completo=True, estado=estado)

    fila = estado.actas_pendientes.pop(0)
    etiqueta = f"{fila.get('service_type_id', '?')} {fila.get('fecha_visita', '')}"
    url = fila["act_pdf_url"]

    descarga = acta_downloader.descargar_pdf_acta(url)
    if not descarga.ok:
        estado.observaciones.append(f"[{etiqueta}] {descarga.motivo_fallo}")
        return ResultadoPaso(completo=not estado.actas_pendientes, estado=estado)

    meta = MetadatosActa(co=normalizar_codigo(fila.get("bia_code", "")), tipo_acta=fila.get("service_type_id", "?"), fecha_visita=fila.get("fecha_visita", ""))

    # Intento 1: solo texto (rápido). Intento 2: PDF completo con imágenes, solo si el texto no
    # trajo todo Y el archivo cabe bajo LIMITE_BYTES_MODO_IMAGEN (Codigo.gs línea 3451/3512).
    spec_final = None
    ocr = acta_ocr.ocr_texto_desde_bytes(descarga.bytes_pdf, drive_cfg)
    if ocr.ok:
        resultado_texto = analizar_acta_desde_texto(meta, ocr.texto, llm)
        if resultado_texto.spec and not _faltan_campos({**estado.spec_combinado, **{k: v for k, v in resultado_texto.spec.items() if v is not None}}):
            spec_final = resultado_texto.spec
        elif resultado_texto.spec:
            spec_final = resultado_texto.spec  # parcial — se combina igual, puede completar entre varias actas

    if spec_final is None and len(descarga.bytes_pdf) < acta_downloader.LIMITE_BYTES_MODO_IMAGEN:
        resultado_imagen = analizar_acta_desde_pdf(meta, descarga.bytes_pdf, llm)
        if resultado_imagen.spec:
            spec_final = resultado_imagen.spec

    if spec_final:
        _combinar_en(estado, fila, etiqueta, spec_final)
    else:
        estado.observaciones.append(f"[{etiqueta}] no se pudo extraer ningún campo (ni texto ni imagen)")

    completo = not estado.actas_pendientes or not _faltan_campos(estado.spec_combinado)
    return ResultadoPaso(completo=completo, estado=estado)
