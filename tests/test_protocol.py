import datetime as dt

import pytest

from src.dates import DateResolver, DateRules
from src.protocol import ProtocolError, parse_response, resolve_periods, substitute

D = dt.date


def test_parse_full_answer():
    d = parse_response("""TYPE: percent
PERIODS: P1 = month:2025-06 ; P2 = prev(P1)
DECIMALS: 2
SQL:
```sql
SELECT 100.0 * (a - b) / b FROM x WHERE {P1:order_date};
```""")
    assert d.type == "percent" and d.periods == {"P1": "month:2025-06", "P2": "prev(P1)"}
    assert d.decimals == 2 and d.sql.startswith("SELECT 100.0") and not d.sql.endswith(";")


def test_parse_multiline_periods_and_table_columns():
    d = parse_response("TYPE: table\nPERIODS:\nP1 = until:2026-08-14\nCOLUMNS: khach_hang, so_tien_no\nSQL:\nSELECT 1")
    assert d.periods == {"P1": "until:2026-08-14"} and d.columns == ["khach_hang", "so_tien_no"]


def test_parse_unanswerable_and_errors():
    d = parse_response("TYPE: unanswerable\nREASON: Dữ liệu không ghi địa chỉ khách.")
    assert d.type == "unanswerable" and "địa chỉ" in d.reason
    with pytest.raises(ProtocolError):
        parse_response("Không biết")
    with pytest.raises(ProtocolError):
        parse_response("TYPE: number\nPERIODS: P1 = today")


def test_sql_keyword_inside_sql_is_not_a_tag():
    d = parse_response("TYPE: number\nSQL:\nSELECT 1\nFROM t\nWHERE reason = 'x'")
    assert "reason" in d.sql


def test_periods_reference_and_substitution():
    r = DateResolver(D(2026, 5, 10))
    ps = resolve_periods({"P1": "month:2026-03", "P2": "prev(P1)"}, r)
    assert ps["P2"].start == D(2026, 2, 1)
    sql = substitute("SELECT 1 FROM t WHERE {P1:o.order_date} AND d < {P1.end} AND {SHIFT:ca_chieu:order_ts}", ps, DateRules())
    assert "o.order_date >= DATE '2026-03-01' AND o.order_date < DATE '2026-04-01'" in sql
    assert "d < DATE '2026-04-01'" in sql and "840" in sql


def test_substitution_errors():
    r = DateResolver(D(2026, 5, 10))
    ps = resolve_periods({"P1": "today"}, r)
    for bad in ["SELECT 1 WHERE d >= '2026-01-01'", "SELECT 1 WHERE {P2:d}", "SELECT current_date",
                "SELECT 1 WHERE {SHIFT:ca_dem:t}", "SELECT {Q1}"]:
        with pytest.raises(ProtocolError):
            substitute(bad, ps, DateRules())
    with pytest.raises(ProtocolError):
        resolve_periods({"P1": "nonsense"}, r)
