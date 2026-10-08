"""Escribe la propuesta de mano de obra (OPEX) ya confirmada en la hoja "OPEX".

Columnas reales confirmadas el 2026-09-22: A=CO, B=(vacía), C=Operador, D=Maniobra,
E=Cantidad, F:M=fórmulas (Costo Unitario MO, Costo total MO, Carro canasta, Descargo,
Acompañamiento, Costo total con extras, -10%, -20%) — la hoja las calcula sola a partir de
Maniobra/Operador/Cantidad, nunca se escriben directo. Además, a la derecha (columnas Q:S) hay
una tabla de referencia de OR/Valor de descargo/Acompañamiento — NO relacionada con la fila de
este CO (misma hoja, tabla aparte) — por eso acá NUNCA se inserta una fila completa (eso
desplazaría esa tabla): se escribe en la siguiente fila ya en blanco, copiando solo A:M desde
la fila anterior para heredar las fórmulas.

ÚNICA excepción a "las fórmulas nunca se escriben": dos columnas llevan un valor FIJO, UNA sola vez
por CO, cuando el alcance trae montaje de TCs/TPs:
- H (Carro canasta): montaje exterior (ver carro_canasta.py).
- I (Descargo): montaje interior o exterior; el valor depende del OR (ver descargo.py).
Como esas celdas dejan de ser fórmula, la fila SIGUIENTE (que se crea copiando la anterior)
heredaría el valor fijo y lo duplicaría: por eso, en toda fila que no lleve ese valor, se
restaura la fórmula de la columna desde la última fila que aún la tiene (cada columna por separado).

K (Desplazamiento, Dinovi 2026-10-08): la hoja la calcula con una fórmula que mira la ciudad de la columna B
(otra fórmula, que depende del CO de la columna A) y pone un precio. El precio de una ciudad se cobra UNA sola
vez entre los CO que se guardan juntos: el primer CO de cada ciudad lo lleva en su primera fila y las demás filas
quedan con K vacía. Por eso (a) ya no se escribe B —antes se escribía "" y se borraba esa fórmula— y (b) después de
escribir la primera fila de cada CO se LEE la ciudad que calculó la hoja. Como la última fila escrita puede quedar con
K vacía, la fila siguiente que sí lleve precio recupera la fórmula desde la última fila que la tiene.
"""

from core.data_sources.sheets_client import SheetsClient
from config.settings import CARRO_CANASTA_MONTAJE_EXTERIOR, SHEET_OPEX
from core.utils import quitar_acentos
from core.services.carro_canasta import indice_fila_carro_canasta
from core.services.descargo import indice_fila_descargo, valor_descargo

_NUM_COLUMNAS_FORMULA_OPEX = 13  # A:M — N/O/P son espaciadores, Q:S son la tabla de referencia aparte
_COL_CARRO_CANASTA = 8  # H (1-indexado)
_COL_DESCARGO = 9  # I
_LETRA_COLUMNA = {_COL_CARRO_CANASTA: "H", _COL_DESCARGO: "I"}
_COL_CIUDAD = 2  # B — fórmula de la hoja (ciudad del CO)
_COL_DESPLAZAMIENTO = 11  # K — fórmula de la hoja (precio según la ciudad de B)


def _es_formula(celda) -> bool:
    return isinstance(celda, str) and celda.startswith("=")


def _es_valor_fijo(celda) -> bool:
    """Celda con algo escrito que NO es fórmula (ej. el 4.500.000 de un CO anterior)."""
    return celda not in (None, "") and not _es_formula(celda)


def _leer_columna_con_formulas(hoja, col: int, ultima_fila_con_datos: int) -> dict:
    """Estado de una columna que a veces lleva valor fijo: en qué fila está su fórmula (la última
    que aún la tiene) y si la fila origen de la copia (la última con datos) ya trae un valor fijo."""
    # value_render_option="FORMULA": hay que ver la fórmula, no el valor calculado.
    valores = hoja.col_values(col, value_render_option="FORMULA")
    fila_formula = next((n for n in range(len(valores), 0, -1) if _es_formula(valores[n - 1])), None)
    origen_fijo = ultima_fila_con_datos <= len(valores) and _es_valor_fijo(valores[ultima_fila_con_datos - 1])
    return {"fila_formula": fila_formula, "origen_fijo": origen_fijo}


def clave_ciudad(valor) -> str:
    """Forma canónica de una ciudad para decidir si dos CO son "la misma" (mayúsculas, acentos y espacios no
    cuentan). Vacía si no hay ciudad o la hoja devolvió un error (#N/A, #REF!…)."""
    texto = " ".join(quitar_acentos(str(valor or "")).lower().split())
    return "" if texto.startswith("#") else texto


def _estado_desplazamiento(hoja, ultima_fila_con_datos: int) -> tuple[int | None, bool]:
    """(fila con la fórmula de K más reciente, ¿la última fila con datos tiene fórmula en K?)."""
    valores = hoja.col_values(_COL_DESPLAZAMIENTO, value_render_option="FORMULA")
    fila_formula = next((n for n in range(len(valores), 0, -1) if _es_formula(valores[n - 1])), None)
    origen_con_formula = ultima_fila_con_datos <= len(valores) and _es_formula(valores[ultima_fila_con_datos - 1])
    return fila_formula, origen_con_formula


def _leer_ciudad(hoja, fila: int) -> str:
    """La ciudad que la HOJA calculó en B de esa fila. Nunca lanza: las filas ya están escritas y un fallo al
    leer no debe dejar el guardado a medias."""
    try:
        celdas = hoja.get(f"B{fila}")
        return str(celdas[0][0]) if celdas and celdas[0] else ""
    except Exception:  # noqa: BLE001
        return ""


def guardar_filas_opex(
    sheets: SheetsClient, co_raw: str, operador: str, filas: list[dict], ciudades_con_desplazamiento: list[str] | None = None,
) -> dict:
    """`filas`: [{"maniobra": str, "cantidad": float}, ...] — el costo lo calcula la hoja.

    Devuelve `carro_canasta` y `descargo`: {"fila", "maniobra", "valor"} de la fila que recibió
    cada uno, o None si el CO no lo lleva.

    `ciudades_con_desplazamiento`: ciudades (ya normalizadas) cuyo desplazamiento se cobró en un CO anterior del
    mismo guardado en bloque; el cliente las va acumulando entre llamadas. Devuelve `desplazamiento`
    ({"ciudad", "aplicado", "fila", "alerta"}, o None si la hoja aún no tiene fórmula en K) y la lista
    `ciudades_con_desplazamiento` ya actualizada.
    """
    if not filas:
        raise ValueError("No hay filas para guardar.")

    hoja = sheets.hoja_por_nombre(SHEET_OPEX)
    ultima_fila_con_datos = len(hoja.col_values(1))  # última fila con algo en A, sin contar el grid vacío de relleno

    maniobras = [f["maniobra"] for f in filas]
    idx_por_columna = {_COL_CARRO_CANASTA: indice_fila_carro_canasta(maniobras), _COL_DESCARGO: indice_fila_descargo(maniobras)}
    valor_por_columna = {_COL_CARRO_CANASTA: CARRO_CANASTA_MONTAJE_EXTERIOR, _COL_DESCARGO: valor_descargo(operador)}
    columnas = {col: _leer_columna_con_formulas(hoja, col, ultima_fila_con_datos) for col in idx_por_columna}

    ya_cobradas = {c for c in (clave_ciudad(x) for x in (ciudades_con_desplazamiento or [])) if c}
    fila_formula_k, k_tiene_formula = _estado_desplazamiento(hoja, ultima_fila_con_datos)
    desplazamiento_activo = fila_formula_k is not None  # si K aún no tiene ninguna fórmula, no hay nada que cuidar
    ciudad_texto, ciudad_clave, lleva_precio, fila_precio, alerta_desp = "", "", True, None, None

    guardadas = []
    asignados: dict[int, dict | None] = {col: None for col in idx_por_columna}
    fila_base = ultima_fila_con_datos
    for i, f in enumerate(filas):
        fila_nueva = fila_base + 1
        if fila_base > 1:
            sheets.copiar_fila(hoja, fila_origen=fila_base, fila_destino=fila_nueva, num_columnas=_NUM_COLUMNAS_FORMULA_OPEX)
        valores_fila = [co_raw, "", operador, f["maniobra"], f.get("cantidad", 1)]
        # Se escribe A y C:E, NUNCA B: B es la fórmula de la ciudad que la copia de arriba ya trajo (antes se
        # escribía "" y se borraba). En las filas siguientes de un CO, K se limpia en la misma petición.
        escrituras = [
            {"range": f"A{fila_nueva}", "values": [[co_raw]]},
            {"range": f"C{fila_nueva}:E{fila_nueva}", "values": [[operador, f["maniobra"], f.get("cantidad", 1)]]},
        ]
        if desplazamiento_activo and i > 0 and ciudad_clave and k_tiene_formula:
            escrituras.append({"range": f"K{fila_nueva}", "values": [[""]]})  # el precio ya quedó en la primera fila
            k_tiene_formula = False
        hoja.batch_update(escrituras, value_input_option="USER_ENTERED")
        guardadas.append(valores_fila)

        if desplazamiento_activo and i == 0:
            ciudad_texto = _leer_ciudad(hoja, fila_nueva)
            ciudad_clave = clave_ciudad(ciudad_texto)
            if not ciudad_clave:
                lleva_precio = True  # sin ciudad no se puede saber si se repite: la fórmula de K queda como está
                alerta_desp = "No se pudo leer la ciudad de la columna B: no se evitó repetir el desplazamiento."
            else:
                lleva_precio = ciudad_clave not in ya_cobradas
                ya_cobradas.add(ciudad_clave)
            if lleva_precio and not k_tiene_formula:
                # La fila anterior terminó con K vacía (precio ya cobrado): se recupera la fórmula.
                sheets.copiar_fila(hoja, fila_origen=fila_formula_k, fila_destino=fila_nueva,
                                   num_columnas=_COL_DESPLAZAMIENTO, col_inicio=_COL_DESPLAZAMIENTO - 1)
                k_tiene_formula = True
            elif not lleva_precio and k_tiene_formula:
                hoja.update([[""]], range_name=f"K{fila_nueva}", value_input_option="USER_ENTERED")
                k_tiene_formula = False
            if lleva_precio and ciudad_clave:
                fila_precio = fila_nueva

        for col, estado in columnas.items():
            if i == idx_por_columna[col]:
                valor = valor_por_columna[col]
                hoja.update([[valor]], range_name=f"{_LETRA_COLUMNA[col]}{fila_nueva}", value_input_option="USER_ENTERED")
                asignados[col] = {"fila": fila_nueva, "maniobra": f["maniobra"], "valor": valor}
                estado["origen_fijo"] = True
                continue
            if fila_base > 1 and estado["origen_fijo"]:
                # La copia de arriba trajo el valor fijo de la fila anterior — se restaura la fórmula.
                if estado["fila_formula"] is not None:
                    sheets.copiar_fila(hoja, fila_origen=estado["fila_formula"], fila_destino=fila_nueva,
                                       num_columnas=col, col_inicio=col - 1)
                else:
                    hoja.update([[""]], range_name=f"{_LETRA_COLUMNA[col]}{fila_nueva}", value_input_option="USER_ENTERED")
            estado["origen_fijo"] = False
        fila_base = fila_nueva

    desplazamiento = None
    if desplazamiento_activo:
        desplazamiento = {
            "ciudad": ciudad_texto or None,
            "aplicado": lleva_precio if ciudad_clave else None,  # None = no se pudo saber (ciudad ilegible)
            "fila": fila_precio, "alerta": alerta_desp,
        }
    return {
        "guardadas": guardadas, "hoja_url": hoja.url,
        "carro_canasta": asignados[_COL_CARRO_CANASTA], "descargo": asignados[_COL_DESCARGO],
        "desplazamiento": desplazamiento, "ciudades_con_desplazamiento": sorted(ya_cobradas),
    }
