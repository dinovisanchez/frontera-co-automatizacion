"""guardar_filas_opex con una hoja falsa — sin Google Sheets real. Verifica dónde se escriben el
Carro canasta (columna H) y el Descargo (columna I), y que la fila siguiente no herede el valor
fijo por la copia A:M."""

from core.services.guardar_opex import guardar_filas_opex

MONTAJE_TCS_EXT = "Montaje  TCs MT (1–3) – exterior"
MONTAJE_TPS_EXT = "Montaje  TPs MT (1–3) – exterior"
MONTAJE_TCS_INT = "Montaje  TCs MT (1–3) – interior"
INSTALACION = "Instalación indirecta exterior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)"
FORMULA_H = "=IFERROR(G2*0;0)"
FORMULA_I = "=IFERROR(VLOOKUP(C2;Q:R;2;0);0)"

CARRO = 4_500_000
DESCARGO = 8_000_000
DESCARGO_ENEL = 12_000_000


class HojaFalsa:
    url = "https://docs.google.com/spreadsheets/d/x/edit#gid=1"

    def __init__(self, col_a: list, col_h: list, col_i: list | None = None):
        self.col_a, self.col_h = col_a, col_h
        # Por defecto la columna I tiene su fórmula en todas las filas de datos.
        self.col_i = col_i if col_i is not None else ["Descargo"] + [FORMULA_I] * (len(col_a) - 1)
        self.escrituras: list[tuple[str, list]] = []  # (rango, valores)

    def col_values(self, col, value_render_option=None):
        assert col in (1, 8, 9)
        if col in (8, 9):
            assert value_render_option == "FORMULA"  # hay que ver la fórmula, no el valor calculado
        return list({1: self.col_a, 8: self.col_h, 9: self.col_i}[col])

    def update(self, *args, range_name=None, **kwargs):
        if isinstance(args[0], str):  # estilo viejo: update("A5:E5", valores)
            rango, valores = args[0], args[1]
        else:
            valores, rango = args[0], range_name
        self.escrituras.append((rango, valores))


class SheetsFalso:
    def __init__(self, hoja):
        self.hoja = hoja
        self.copias: list[dict] = []

    def hoja_por_nombre(self, nombre):
        assert nombre == "OPEX"
        return self.hoja

    def copiar_fila(self, hoja, fila_origen, fila_destino, num_columnas, col_inicio=0):
        self.copias.append({"origen": fila_origen, "destino": fila_destino, "num_columnas": num_columnas, "col_inicio": col_inicio})


def _hoja_con_un_co_previo(h_ultima_fila=FORMULA_H, i_ultima_fila=FORMULA_I):
    # Fila 1 = encabezado; filas 2-3 = un CO anterior. H e I tienen fórmula (salvo lo que se indique).
    return HojaFalsa(
        col_a=["CO", "CO0000000001", "CO0000000001"],
        col_h=["Carro canasta", FORMULA_H, h_ultima_fila],
        col_i=["Descargo", FORMULA_I, i_ultima_fila],
    )


def _escrituras_col(hoja, letra):
    return [(r, v) for r, v in hoja.escrituras if r.startswith(letra) and not r.startswith("A")]


def _restauraciones(sheets, col_inicio):
    return [(c["origen"], c["destino"]) for c in sheets.copias if c["col_inicio"] == col_inicio]


def _filas(*maniobras):
    return [{"maniobra": m, "cantidad": 1} for m in maniobras]


# ------------------------------------------------------------------ Carro canasta (H)

def test_sin_montaje_no_toca_h_ni_i():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION, "Cambio de DPS (unidad)"))

    assert res["carro_canasta"] is None and res["descargo"] is None
    assert _escrituras_col(hoja, "H") == [] and _escrituras_col(hoja, "I") == []
    assert [c["col_inicio"] for c in sheets.copias] == [0, 0]  # solo las copias A:M de siempre
    assert [(c["origen"], c["destino"]) for c in sheets.copias] == [(3, 4), (4, 5)]


def test_montaje_exterior_escribe_el_carro_canasta_en_h_de_esa_fila():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION, MONTAJE_TCS_EXT))

    # Filas nuevas: 4 (instalación) y 5 (montaje). Ambos valores fijos van SOLO en la 5.
    assert _escrituras_col(hoja, "H") == [("H5", [[CARRO]])]
    assert res["carro_canasta"] == {"fila": 5, "maniobra": MONTAJE_TCS_EXT, "valor": CARRO}
    assert res["guardadas"][1] == ["CO0100002908", "", "AFINIA", MONTAJE_TCS_EXT, 1]


def test_montaje_interior_no_lleva_carro_canasta_pero_si_descargo():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(MONTAJE_TCS_INT))

    assert res["carro_canasta"] is None and _escrituras_col(hoja, "H") == []
    assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO]])]
    assert res["descargo"] == {"fila": 4, "maniobra": MONTAJE_TCS_INT, "valor": DESCARGO}


# ------------------------------------------------------------------ Descargo (I)

def test_descargo_es_de_8_millones_para_cualquier_or_que_no_sea_enel():
    for operador in ("AFINIA", "EMCALI", "AIRE", "ESSA", "CELSIA VALLE", "ELECTROHUILA", "OTROS_OR"):
        hoja = _hoja_con_un_co_previo()
        res = guardar_filas_opex(SheetsFalso(hoja), "CO0100002908", operador, _filas(MONTAJE_TCS_INT))
        assert res["descargo"]["valor"] == DESCARGO, operador
        assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO]])], operador


def test_descargo_es_de_12_millones_para_enel():
    hoja = _hoja_con_un_co_previo()

    res = guardar_filas_opex(SheetsFalso(hoja), "CO0100002908", "ENEL", _filas(MONTAJE_TCS_EXT))

    assert res["descargo"] == {"fila": 4, "maniobra": MONTAJE_TCS_EXT, "valor": DESCARGO_ENEL}
    assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO_ENEL]])]
    assert res["carro_canasta"]["valor"] == CARRO  # el carro canasta NO cambia con el OR


def test_descargo_una_sola_vez_por_co_aunque_haya_montaje_de_tc_y_de_tp():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(MONTAJE_TCS_EXT, MONTAJE_TPS_EXT))

    assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO]])]
    assert res["descargo"]["fila"] == 4


def test_descargo_va_en_el_primer_montaje_aunque_el_carro_canasta_vaya_en_otro():
    # Primero un montaje INTERIOR (solo descargo) y después uno EXTERIOR (carro canasta; el descargo
    # ya se puso en la fila anterior). Cada columna elige su propia fila.
    hoja = _hoja_con_un_co_previo()

    res = guardar_filas_opex(SheetsFalso(hoja), "CO0100002908", "AFINIA", _filas(MONTAJE_TCS_INT, MONTAJE_TPS_EXT))

    assert res["descargo"]["fila"] == 4 and res["carro_canasta"]["fila"] == 5
    assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO]])]
    assert _escrituras_col(hoja, "H") == [("H5", [[CARRO]])]


# ------------------------------------------------------------------ Herencia de la fila anterior

def test_tc_y_tp_exterior_las_filas_siguientes_recuperan_las_formulas():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(MONTAJE_TCS_EXT, MONTAJE_TPS_EXT))

    assert _escrituras_col(hoja, "H") == [("H4", [[CARRO]])]  # un solo carro canasta por CO
    # La fila 5 se copió desde la 4 (que ya tiene los valores fijos): se le restaura la fórmula de
    # cada columna desde la última fila con fórmula (la 3), copiando SOLO esa columna.
    assert _restauraciones(sheets, 7) == [(3, 5)]  # H = índices 7 a 8
    assert _restauraciones(sheets, 8) == [(3, 5)]  # I = índices 8 a 9
    assert {"origen": 3, "destino": 5, "num_columnas": 8, "col_inicio": 7} in sheets.copias
    assert {"origen": 3, "destino": 5, "num_columnas": 9, "col_inicio": 8} in sheets.copias


def test_el_co_siguiente_no_hereda_los_valores_fijos_del_co_anterior():
    # El CO previo terminó con carro canasta Y descargo fijos en su última fila (3); las fórmulas
    # siguen en la 2.
    hoja = _hoja_con_un_co_previo(h_ultima_fila=CARRO, i_ultima_fila=DESCARGO)
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION, "Cambio de DPS (unidad)"))

    assert res["carro_canasta"] is None and res["descargo"] is None
    assert _escrituras_col(hoja, "H") == [] and _escrituras_col(hoja, "I") == []
    # La fila 4 (copiada de la 3, con los valores fijos) recupera cada fórmula desde la fila 2. La
    # fila 5 se copia de la 4, que ya las tiene: no hace falta restaurar de nuevo.
    assert _restauraciones(sheets, 7) == [(2, 4)]
    assert _restauraciones(sheets, 8) == [(2, 4)]


def test_solo_se_restaura_la_columna_que_heredo_un_valor_fijo():
    # Solo el descargo quedó fijo en el CO anterior (p. ej. montaje interior): H no se toca.
    hoja = _hoja_con_un_co_previo(i_ultima_fila=DESCARGO)
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION))

    assert _restauraciones(sheets, 7) == []
    assert _restauraciones(sheets, 8) == [(2, 4)]


def test_sin_ninguna_formula_se_limpia_el_valor_heredado():
    hoja = HojaFalsa(
        col_a=["CO", "CO0000000001"], col_h=["Carro canasta", CARRO], col_i=["Descargo", DESCARGO],
    )
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION))

    assert _escrituras_col(hoja, "H") == [("H3", [[""]])]
    assert _escrituras_col(hoja, "I") == [("I3", [[""]])]
    assert all(c["col_inicio"] == 0 for c in sheets.copias)


def test_celda_vacia_en_la_fila_origen_no_se_toca():
    # Si la H/I de la fila anterior está vacía (no es un valor fijo) no hay nada que restaurar.
    hoja = HojaFalsa(
        col_a=["CO", "CO0000000001", "CO0000000001"],
        col_h=["Carro canasta", FORMULA_H, ""], col_i=["Descargo", FORMULA_I, ""],
    )
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION))

    assert _escrituras_col(hoja, "H") == [] and _escrituras_col(hoja, "I") == []
    assert [c["col_inicio"] for c in sheets.copias] == [0]
