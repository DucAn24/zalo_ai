from src.matcher import Score, is_correct


def G(t, a, alias=None):
    return {"type": t, "answer": a, "alias": alias or []}


def P(t, a=None):
    d = {"type": t}
    if a is not None:
        d["answer"] = a
    return d


def test_numbers_exact():
    assert is_correct(P("number", 48250000), G("number", 48250000))
    assert is_correct(P("number", 48250000.0000000001), G("number", 48250000))
    assert not is_correct(P("number", 48250001), G("number", 48250000))
    assert not is_correct(P("number", "48250000"), G("number", 48250000))
    assert not is_correct(P("percent", 12.4), G("number", 12.4))       # wrong type
    assert is_correct(P("percent", -12.45), G("percent", -12.45))
    assert not is_correct(P("percent", 12.45), G("percent", -12.45))   # sign


def test_strings_norm_alias():
    g = G("string", "Sting dâu 330ml", ["SP0007"])
    assert is_correct(P("string", "sting   DÂU 330ML!"), g)
    assert is_correct(P("string", "sp0007"), g)
    assert not is_correct(P("string", "Sting dầu 330ml"), g)          # wrong diacritic
    assert not is_correct(P("string", ["Sting dâu 330ml"]), g)


def test_date_bool():
    assert is_correct(P("date", "2025-05-10"), G("date", "2025-05-10"))
    assert not is_correct(P("date", "10/05/2025"), G("date", "2025-05-10"))
    assert is_correct(P("date", "2025-05"), G("date", "2025-05"))
    assert is_correct(P("boolean", True), G("boolean", True))
    assert not is_correct(P("boolean", 1), G("boolean", True))


def test_list_order_and_alias():
    g = G("list", ["Cao Long Minh", "Ông Quang Hoàng"], [["KH0112"], []])
    assert is_correct(P("list", ["KH0112", "ông quang hoàng"]), g)
    assert not is_correct(P("list", ["Ông Quang Hoàng", "Cao Long Minh"]), g)
    assert not is_correct(P("list", ["Cao Long Minh"]), g)
    assert is_correct(P("list", [8, 8]), G("list", [8, 8]))


def test_table_rows_as_set_columns_by_name():
    g = G("table", {"columns": ["khach_hang", "so_tien_no"], "rows": [["Lan", 3200000], ["Minh", 100]]},
          [["KH01"], []])
    assert is_correct(P("table", {"columns": ["khach_hang", "so_tien_no"], "rows": [["Minh", 100], ["KH01", 3200000]]}), g)
    assert is_correct(P("table", {"columns": ["so_tien_no", "khach_hang"], "rows": [[100, "Minh"], [3200000, "Lan"]]}), g)
    # unknown column names -> positional
    assert is_correct(P("table", {"columns": ["ten", "no"], "rows": [["Lan", 3200000], ["Minh", 100]]}), g)
    assert not is_correct(P("table", {"columns": ["khach_hang", "so_tien_no"], "rows": [["Lan", 3200000]]}), g)
    assert not is_correct(P("table", {"columns": ["khach_hang", "so_tien_no"], "rows": [["Lan", "3.200.000"], ["Minh", 100]]}), g)


def test_unanswerable_and_abstain():
    gu = G("unanswerable", None)
    assert is_correct(P("unanswerable"), gu)
    assert not is_correct(P("number", 0), gu)
    assert not is_correct(P("unanswerable"), G("number", 5))
    assert is_correct(P("abstain"), G("number", 5)) is None
    assert is_correct(None, G("number", 5)) is None


def test_pa():
    s = Score()
    for ok in (True, True, False, None):
        s.add(ok)
    assert s.pa(1.0) == (2 - 1) / 4
    assert s.pa(0.5) == (2 - 0.5) / 4
