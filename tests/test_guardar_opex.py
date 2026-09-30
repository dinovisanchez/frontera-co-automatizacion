"""guardar_filas_opex con una hoja falsa — sin Google Sheets real. Verifica dónde se escribe el
Carro canasta (columna H) y que la fila siguiente no herede el valor fijo por la copia A:M."""

from core.services.guardar_opex import guardar_filas_opex

MONTAJE_TCS_EXT = "Montaje  TCs MT (1–3) – exterior"
MONTAJE_TPS_EXT = "Montaje  TPs MT (1–3) – exterior"
MONTAJE_TCS_INT = "Montaje  TCs MT (1–3) – interior"
INSTALACION = "Instalación indirecta exterior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)"
FORMULA_H = "=IFERROR(G2*0;0)"


class HojaFalsa:
    url = "https://docs.google.com/spreadsheets/d/x/edit#gid=1"

    def __init__(self, col_a: list, col_h: list):
        self.col_a, self.col_h = col_a, col_h
        self.escrituras: list[tuple[str, list]] = []  # (rango, valores)

    def col_values(self, col, value_render_option=None):
        assert col in (1, 8)
        if col == 8:
            assert value_render_option == "FORMULA"  # hay que ver la fórmula, no el valor calculado
        return list(self.col_a if col == 1 else self.col_h)

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


def _hoja_con_un_co_previo(h_ultima_fila=FORMULA_H):
    # Fila 1 = encabezado; filas 2-3 = un CO anterior. H tiene fórmula (salvo lo que se indique).
    return HojaFalsa(
        col_a=["CO", "CO0000000001", "CO0000000001"],
        col_h=["Carro canasta", FORMULA_H, h_ultima_fila],
    )


def _escrituras_h(hoja):
    return [(r, v) for r, v in hoja.escrituras if r.startswith("H")]


def test_sin_montaje_exterior_no_toca_la_columna_h():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", [{"maniobra": MONTAJE_TCS_INT, "cantidad": 1}, {"maniobra": INSTALACION, "cantidad": 1}])

    assert res["carro_canasta"] is None
    assert _escrituras_h(hoja) == []
    assert [c["col_inicio"] for c in sheets.copias] == [0, 0]  # solo las copias A:M de siempre
    assert [(c["origen"], c["destino"]) for c in sheets.copias] == [(3, 4), (4, 5)]


def test_montaje_exterior_escribe_el_valor_fijo_en_h_de_esa_fila():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", [{"maniobra": INSTALACION, "cantidad": 1}, {"maniobra": MONTAJE_TCS_EXT, "cantidad": 1}])

    # Filas nuevas: 4 (instalación) y 5 (montaje). El carro canasta va SOLO en la 5.
    assert _escrituras_h(hoja) == [("H5", [[4_500_000]])]
    assert res["carro_canasta"] == {"fila": 5, "maniobra": MONTAJE_TCS_EXT, "valor": 4_500_000}
    assert res["guardadas"][1] == ["CO0100002908", "", "AFINIA", MONTAJE_TCS_EXT, 1]


def test_tc_y_tp_exterior_solo_la_primera_lleva_el_valor_y_la_segunda_recupera_la_formula():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", [{"maniobra": MONTAJE_TCS_EXT, "cantidad": 1}, {"maniobra": MONTAJE_TPS_EXT, "cantidad": 1}])

    assert _escrituras_h(hoja) == [("H4", [[4_500_000]])]  # un solo valor por CO
    assert res["carro_canasta"]["fila"] == 4
    # La fila 5 se copió desde la 4 (que ya tiene el valor fijo): se le restaura la fórmula de H
    # desde la última fila con fórmula (la 3), copiando SOLO la columna H (índices 7 a 8).
    assert sheets.copias[-1] == {"origen": 3, "destino": 5, "num_columnas": 8, "col_inicio": 7}


def test_el_co_siguiente_no_hereda_el_valor_fijo_del_co_anterior():
    # El CO previo terminó con el carro canasta fijo en su última fila (3); la fórmula sigue en la 2.
    hoja = _hoja_con_un_co_previo(h_ultima_fila=4_500_000)
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", [{"maniobra": MONTAJE_TCS_INT, "cantidad": 1}, {"maniobra": INSTALACION, "cantidad": 1}])

    assert res["carro_canasta"] is None
    assert _escrituras_h(hoja) == []
    # La fila 4 (copiada de la 3, con el valor fijo) recupera la fórmula de H desde la fila 2, la
    # última con fórmula. La fila 5 se copia de la 4, que ya la tiene: no hace falta restaurar.
    restauraciones = [c for c in sheets.copias if c["col_inicio"] == 7]
    assert [(c["origen"], c["destino"]) for c in restauraciones] == [(2, 4)]


def test_sin_ninguna_formula_en_h_se_limpia_el_valor_heredado():
    hoja = HojaFalsa(col_a=["CO", "CO0000000001"], col_h=["Carro canasta", 4_500_000])
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", [{"maniobra": INSTALACION, "cantidad": 1}])

    assert _escrituras_h(hoja) == [("H3", [[""]])]
    assert all(c["col_inicio"] == 0 for c in sheets.copias)


def test_h_vacia_en_la_fila_origen_no_se_toca():
    # Si la H de la fila anterior está vacía (no es un valor fijo) no hay nada que restaurar.
    hoja = HojaFalsa(col_a=["CO", "CO0000000001", "CO0000000001"], col_h=["Carro canasta", FORMULA_H, ""])
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", [{"maniobra": INSTALACION, "cantidad": 1}])

    assert _escrituras_h(hoja) == []
    assert [c["col_inicio"] for c in sheets.copias] == [0]
