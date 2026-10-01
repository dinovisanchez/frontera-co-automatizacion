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
from core.data_sources.sheets_client import SheetsClient
from core.prompts.acta_extraction_prompt import CAMPOS_A_COMBINAR_ALCANCE, TIPOS_ACTA_ALCANCE
from core.services import acta_downloader, acta_ocr
from core.services.acta_analyzer import MetadatosActa, analizar_acta_desde_pdf, analizar_acta_desde_texto
from core.services.acta_cache import get_acta_cache
from core.services.job_store import EstadoJob
from core.utils import normalizar_codigo, quitar_acentos

# Regla de selección (Dinovi, 2026-10-01: "no revises todas las actas"): UNA sola acta por CO —
# la INFR de una visita exitosa; si no hay INFR exitosa, la más reciente de cualquier tipo que
# sea exitosa. Antes se leían hasta 5 (la más nueva primero) hasta completar los campos, lo que
# multiplicaba el costo de Claude por 2-5 y no era la regla de negocio.
MAX_ACTAS_A_ESCANEAR = 1
TIPO_ACTA_PREFERIDA = "INFR"
COLUMNA_ESTADO_VISITA = "estado_visita"  # columna de la Card 82534 de Metabase
ESTADO_VISITA_EXITOSA = "Cierre Exitoso"
# "Bono": se toman si alguna acta los trae, pero no detienen el escaneo por sí solos.
_CAMPOS_BONO = ("relacion_tc", "relacion_tp", "montaje_tc", "totalizador_amperios", "conductor_calibre")


@dataclass
class ResultadoPaso:
    completo: bool
    estado: EstadoJob


def hay_acta_instalacion(filas_metabase_co: list[dict]) -> bool:
    """Existe o no una acta tipo INST para el CO — independiente de si el bucle de pasos llega
    a leerla (puede detenerse antes si otra acta más reciente ya llenó los campos). Se calcula
    sobre TODAS las filas de Metabase que califican, no solo las seleccionadas para leer."""
    return any(
        (r.get("service_type_id") or "").upper() == "INST"
        for r in filas_metabase_co
        if (r.get("service_type_id") or "").upper() in TIPOS_ACTA_ALCANCE
    )


def _normalizar_estado(s) -> str:
    return " ".join(quitar_acentos(str(s or "")).lower().split())


def es_visita_exitosa(fila: dict) -> bool:
    return _normalizar_estado(fila.get(COLUMNA_ESTADO_VISITA)) == _normalizar_estado(ESTADO_VISITA_EXITOSA)


def _filas_con_acta(filas_metabase_co: list[dict]) -> list[dict]:
    filas = [
        r for r in filas_metabase_co
        if (r.get("service_type_id") or "").upper() in TIPOS_ACTA_ALCANCE and r.get("act_pdf_url")
    ]
    # Si la columna ni siquiera existe, filtrar por ella descartaría TODAS las actas en silencio y
    # cada CO parecería "sin actas": mejor fallar con el motivo a la vista.
    if filas and not any(COLUMNA_ESTADO_VISITA in r for r in filas):
        raise RuntimeError(f'La tarjeta de Metabase no trae la columna "{COLUMNA_ESTADO_VISITA}" (columnas: {sorted(filas[0])}).')
    return filas


def seleccionar_acta(filas_metabase_co: list[dict]) -> dict | None:
    """La ÚNICA acta que se lee de un CO: la INFR exitosa más reciente; si no hay INFR exitosa, la
    exitosa más reciente de cualquier tipo; None si ninguna visita con acta fue exitosa."""
    exitosas = [r for r in _filas_con_acta(filas_metabase_co) if es_visita_exitosa(r)]
    infr = [r for r in exitosas if (r.get("service_type_id") or "").upper() == TIPO_ACTA_PREFERIDA]
    elegibles = infr or exitosas
    return max(elegibles, key=lambda r: r.get("fecha_visita") or "") if elegibles else None


def preparar_actas_pendientes(co: str, filas_metabase_co: list[dict]) -> list[dict]:
    """Lista de actas por leer del CO: [la acta elegida] o [] (ver seleccionar_acta). Se conserva
    como lista porque el job de actas (actas_pendientes) y sus llamadores trabajan sobre una cola."""
    acta = seleccionar_acta(filas_metabase_co)
    return [acta] if acta else []


def motivo_sin_acta(co: str, filas_metabase_co: list[dict]) -> str:
    """Mensaje cuando preparar_actas_pendientes devuelve []: por qué no hay acta que leer. Empieza con
    "no tiene ninguna acta" porque el frontend lo reconoce para pasar al modo "sin actas"."""
    filas = _filas_con_acta(filas_metabase_co)
    if not filas:
        return f'"{co}" no tiene ninguna acta {"/".join(sorted(TIPOS_ACTA_ALCANCE))} con act_pdf_url.'
    estados = sorted({str(r.get(COLUMNA_ESTADO_VISITA) or "(vacío)") for r in filas})
    return (f'"{co}" no tiene ninguna acta de una visita exitosa ({COLUMNA_ESTADO_VISITA} = "{ESTADO_VISITA_EXITOSA}"): '
            f'tiene {len(filas)} fila(s) con acta, con estado(s): {", ".join(estados)}.')


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

    if spec.get("capacidad_instalada_kva") is not None:
        estado.capacidades_vistas.append({"valor": spec["capacidad_instalada_kva"], "etiqueta": etiqueta})
        if "capacidad_instalada_kva" not in aportados:
            aportados.append("capacidad_instalada_kva (adicional, para cruzar)")

    for c in _CAMPOS_BONO:
        if estado.spec_combinado.get(c) is None and spec.get(c) is not None:
            estado.spec_combinado[c] = spec[c]
            aportados.append(c)
    if spec.get("relacion_tc") is not None:
        estado.relaciones_tc_vistas.append({"valor": spec["relacion_tc"], "etiqueta": etiqueta})
        if "relacion_tc" not in aportados:
            aportados.append("relacion_tc (adicional, para cruzar)")
    if spec.get("observaciones"):
        estado.observaciones.append(f"[{etiqueta}] {spec['observaciones']}")

    estado.actas_usadas.append({
        "url": fila["act_pdf_url"], "tipo": fila.get("service_type_id"),
        "fecha": fila.get("fecha_visita"), "aporte": aportados,
    })


def procesar_siguiente_acta(
    estado: EstadoJob, llm: AnthropicClient, drive_cfg, sheets: SheetsClient | None = None,
    permitir_modo_imagen: bool = True,
) -> ResultadoPaso:
    """Procesa UNA acta de estado.actas_pendientes (la más reciente primero) y actualiza
    estado.spec_combinado in-place. Devuelve completo=True cuando ya no hace falta seguir
    (todos los CAMPOS_A_COMBINAR_ALCANCE + relacion_tc si aplica, o ya no quedan actas).

    `sheets` (opcional, Dinovi 2026-09-23 — reanalizar un CO no debe volver a pagar
    descarga+OCR+LLM de una acta YA leída antes): si se pasa, consulta/llena acta_cache.py por
    `act_pdf_url` ANTES de descargar. Se deja opcional para no romper llamadas existentes.

    `permitir_modo_imagen` (Dinovi, 2026-09-24 — comparación masiva de ~400 CO): en False,
    NUNCA se manda el PDF completo (con fotos) a Claude como fallback — solo el texto OCR ya
    extraído. Una acta cuyo texto no alcance para llenar un campo simplemente queda incompleta
    en ese campo, igual que cuando ya falta esa información hoy.
    """
    if not estado.actas_pendientes or not _faltan_campos(estado.spec_combinado):
        return ResultadoPaso(completo=True, estado=estado)

    fila = estado.actas_pendientes.pop(0)
    etiqueta = f"{fila.get('service_type_id', '?')} {fila.get('fecha_visita', '')}"
    url = fila["act_pdf_url"]
    cache = get_acta_cache(sheets) if sheets is not None else None

    spec_final = cache.obtener(url) if cache else None
    if spec_final is not None:
        etiqueta += " (caché)"
    else:
        descarga = acta_downloader.descargar_pdf_acta(url)
        if not descarga.ok:
            estado.observaciones.append(f"[{etiqueta}] {descarga.motivo_fallo}")
            return ResultadoPaso(completo=not estado.actas_pendientes, estado=estado)

        meta = MetadatosActa(co=normalizar_codigo(fila.get("bia_code", "")), tipo_acta=fila.get("service_type_id", "?"), fecha_visita=fila.get("fecha_visita", ""))

        # Intento 1: solo texto (rápido). Intento 2: PDF completo con imágenes, solo si el texto
        # no trajo todo Y el archivo cabe bajo LIMITE_BYTES_MODO_IMAGEN (Codigo.gs línea 3451/3512).
        ocr = acta_ocr.ocr_texto_desde_bytes(descarga.bytes_pdf, drive_cfg)
        if ocr.ok:
            resultado_texto = analizar_acta_desde_texto(meta, ocr.texto, llm)
            if resultado_texto.spec and not _faltan_campos({**estado.spec_combinado, **{k: v for k, v in resultado_texto.spec.items() if v is not None}}):
                spec_final = resultado_texto.spec
            elif resultado_texto.spec:
                spec_final = resultado_texto.spec  # parcial — se combina igual, puede completar entre varias actas

        if permitir_modo_imagen and spec_final is None and len(descarga.bytes_pdf) < acta_downloader.LIMITE_BYTES_MODO_IMAGEN:
            resultado_imagen = analizar_acta_desde_pdf(meta, descarga.bytes_pdf, llm)
            if resultado_imagen.spec:
                spec_final = resultado_imagen.spec

        if spec_final and cache:
            cache.guardar(url, spec_final)

    if spec_final:
        _combinar_en(estado, fila, etiqueta, spec_final)
    else:
        estado.observaciones.append(f"[{etiqueta}] no se pudo extraer ningún campo (ni texto ni imagen)")

    completo = not estado.actas_pendientes or not _faltan_campos(estado.spec_combinado)
    return ResultadoPaso(completo=completo, estado=estado)


def acta_resultado_desde_estado(estado: EstadoJob) -> dict | None:
    """Convierte el EstadoJob (progreso crudo del job de actas) al `acta_resultado` que espera
    analizar_alcance_provisional — movido acá (antes vivía privado en api/analizar_alcance.py)
    para que lote_store.py (comparación masiva, Dinovi 2026-09-24) lo reutilice sin duplicarlo
    ni depender de la capa api/."""
    if not estado.actas_usadas:
        return None
    ultima = estado.actas_usadas[0]

    def _distintos(vistos: list[dict]) -> list[dict] | None:
        vistos_unicos = []
        valores = set()
        for v in vistos:
            if v["valor"] not in valores:
                vistos_unicos.append(v)
                valores.add(v["valor"])
        return vistos_unicos if len(vistos_unicos) > 1 else None

    return {
        "spec": estado.spec_combinado, "observaciones": estado.observaciones, "actas": estado.actas_usadas,
        "acta_url": ultima["url"], "tipo_acta": ultima["tipo"], "fecha_acta": ultima["fecha"],
        "tiene_acta_instalacion": estado.tiene_acta_instalacion,
        "capacidades_encontradas": _distintos(estado.capacidades_vistas),
        "relaciones_tc_encontradas": _distintos(estado.relaciones_tc_vistas),
        "cortado_por_tiempo": False,
    }
