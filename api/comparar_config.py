"""POST /api/comparar_config — compara la extracción de UNA acta de un CO con la configuración
actual (modelo + esfuerzo) y con 1-3 candidatas, sobre el MISMO texto OCR. Ver comparador.py.

Body: {"co": "CO0100002908", "indice": 0, "candidatas": ["opus-5-5-medio", "sonnet-5-5-medio"]}
  `indice`: desde qué candidata empezar (0 = la que producción leería: la INFR exitosa o la más reciente
  exitosa; ver alcance_combiner.seleccionar_actas_ordenadas). Igual que producción, si esa acta no se puede
  descargar o leer (PDF inválido, muy grande, OCR caído) se prueba la siguiente candidata, mientras quede
  tiempo; las omitidas vuelven en `omitidas`. Descarga + OCR + (1 + candidatas) llamadas a Claude en
  paralelo caben en los 60 s de Vercel.

GASTA API de Claude (≈ una extracción por configuración); no guarda nada en las hojas de trabajo,
solo deja el consumo en "PyConsumo" con origen "comparacion".
"""

import time

from flask import Blueprint, jsonify, request

from config.settings import cargar_anthropic_config
from core.services import acta_downloader, acta_ocr, alcance_combiner
from core.services.acta_analyzer import MetadatosActa
from core.services.comparador import CONFIGS_CANDIDATAS, MAX_CANDIDATAS, comparar_acta_texto
from core.services.consumo import get_consumo_store
from core.services.wiring import construir_dependencias
from core.utils import normalizar_codigo

bp = Blueprint("comparar_config", __name__)

# La función de Vercel muere a los 60 s (vercel.json) y entrega un 504 SIN resultado. Se reserva un
# margen y lo que quede después de descargar + leer el acta es el tiempo máximo de Claude; si ya no
# alcanza para una llamada razonable, NO se llama a Claude (no se gasta nada) y se avisa.
PRESUPUESTO_SEG = 55
MARGEN_SEG = 5
MIN_SEG_PARA_CLAUDE = 15
MAX_SEG_POR_LLAMADA = 45
UMBRAL_PROBAR_OTRA_ACTA_SEG = 25  # pasado este tiempo, un nuevo intento de descarga + OCR ya no cabe


@bp.post("/api/comparar_config")
def comparar_config():
    inicio = time.monotonic()
    body = request.get_json(force=True, silent=True) or {}
    co_raw = body.get("co")
    if not co_raw:
        return jsonify({"error": "El código CO es obligatorio."}), 400
    co = normalizar_codigo(co_raw)

    candidatas = body.get("candidatas") or []
    if not isinstance(candidatas, list) or not (1 <= len(candidatas) <= MAX_CANDIDATAS) or any(c not in CONFIGS_CANDIDATAS for c in candidatas):
        return jsonify({"error": f"\"candidatas\" debe traer de 1 a {MAX_CANDIDATAS} de: {sorted(CONFIGS_CANDIDATAS)}."}), 400
    candidatas = list(dict.fromkeys(candidatas))  # sin repetidas, conservando el orden

    indice = body.get("indice", 0)
    if not isinstance(indice, int) or isinstance(indice, bool) or not (0 <= indice < alcance_combiner.MAX_ACTAS_A_ESCANEAR):
        return jsonify({"error": f'"indice" debe ser un entero entre 0 y {alcance_combiner.MAX_ACTAS_A_ESCANEAR - 1}.'}), 400

    deps = construir_dependencias()
    if deps.metabase is None:
        return jsonify({"error": "Metabase no está configurado (METABASE_URL/METABASE_API_KEY/METABASE_CARD_ID)."}), 500

    filas_metabase_co = deps.metabase.filas_por_co(co)
    if not filas_metabase_co:
        return jsonify({"error": f'No encontré filas de "{co}" en Metabase.'}), 404
    actas = alcance_combiner.preparar_actas_pendientes(co, filas_metabase_co)
    if not actas:
        return jsonify({"error": alcance_combiner.motivo_sin_acta(co, filas_metabase_co)}), 404
    if indice >= len(actas):
        return jsonify({"co": co, "total_actas": len(actas), "sin_acta": True})

    # Falla técnica (descarga u OCR) → siguiente candidata, como en producción; solo mientras quede tiempo.
    omitidas, fila, acta, ocr = [], None, None, None
    for pos in range(indice, len(actas)):
        if omitidas and time.monotonic() - inicio > UMBRAL_PROBAR_OTRA_ACTA_SEG:
            break
        candidata = actas[pos]
        info = {"indice": pos, "tipo": candidata.get("service_type_id"), "fecha": candidata.get("fecha_visita"), "url": candidata["act_pdf_url"]}
        descarga = acta_downloader.descargar_pdf_acta(candidata["act_pdf_url"])
        if not descarga.ok:
            omitidas.append({**info, "motivo": f"No se pudo descargar: {descarga.motivo_fallo}"})
            continue
        lectura = acta_ocr.ocr_texto_desde_bytes(descarga.bytes_pdf, deps.drive_cfg)
        if not lectura.ok:
            omitidas.append({**info, "motivo": f"El OCR falló: {lectura.motivo_fallo}"})
            continue
        fila, acta, ocr = candidata, info, lectura
        break
    if ocr is None:
        detalle = "; ".join(f"{o['tipo']} {o['fecha']}: {o['motivo']}" for o in omitidas)
        return jsonify({"co": co, "total_actas": len(actas), "omitidas": omitidas, "error": f"No se pudo leer ninguna acta candidata ({detalle}). Si quedó sin tiempo, reintenta este CO."})

    restante = PRESUPUESTO_SEG - (time.monotonic() - inicio)
    if restante < MIN_SEG_PARA_CLAUDE + MARGEN_SEG:
        return jsonify({"co": co, "total_actas": len(actas), "acta": acta, "error": (
            f"Descargar y leer el acta tardó demasiado ({PRESUPUESTO_SEG - restante:.0f} s) y ya no quedaba tiempo para llamar a Claude. "
            "No se gastó nada. Reintenta este CO.")})
    timeout_seg = min(MAX_SEG_POR_LLAMADA, restante - MARGEN_SEG)

    meta = MetadatosActa(co=co, tipo_acta=fila.get("service_type_id", "?"), fecha_visita=fila.get("fecha_visita", ""))
    resultado = comparar_acta_texto(meta, ocr.texto, cargar_anthropic_config(), candidatas, timeout_seg=timeout_seg)

    # El consumo de la comparación queda en PyConsumo (origen "comparacion"), en secuencia.
    store = get_consumo_store(deps.sheets)
    for cfg in resultado["configuraciones"]:
        for registro in cfg.pop("registros"):
            store.registrar({**registro, "co": co, "tipo": "acta_texto", "acta": acta["tipo"]})

    return jsonify({"co": co, "total_actas": len(actas), "acta": acta, "omitidas": omitidas, "ocr_caracteres": len(ocr.texto), **resultado})
