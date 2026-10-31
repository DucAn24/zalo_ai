import datetime as dt

import pandas as pd
import pytest

from src.canon import Business
from src.sandbox import Sandbox, SandboxError, check_sql


def make_biz():
    b = Business(biz_id="t")
    b.tables["orders"] = pd.DataFrame({
        "order_id": ["O1", "O2", "O3"],
        "order_date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-02-01"]),
        "status": ["hoan_thanh", "huy", "hoan_thanh"],
        "items_amount": [100.0, 50.0, 70.0],
        "order_time": [dt.time(8, 0), None, dt.time(15, 0)],
    })
    b.raw["raw_x"] = pd.DataFrame({"a": ["1", "x", None], "b": [1, 2, 3]})
    return b


def test_select_and_types():
    sb = Sandbox(make_biz())
    df = sb.run("SELECT SUM(items_amount) AS s FROM orders WHERE status <> 'huy' "
                "AND order_date >= DATE '2025-01-01' AND order_date < DATE '2025-02-01'")
    assert df.iat[0, 0] == 100.0
    assert sb.run("SELECT typeof(order_date) t FROM orders LIMIT 1").iat[0, 0] == "DATE"
    assert sb.run("SELECT count(*) FROM raw_x").iat[0, 0] == 3


@pytest.mark.parametrize("sql", [
    "DROP TABLE orders", "SELECT 1; SELECT 2", "COPY orders TO 'x.csv'", "ATTACH 'x.db'",
    "SELECT * FROM read_csv_auto('/etc/passwd')", "INSTALL httpfs", "PRAGMA version", "SET threads=1",
])
def test_forbidden(sql):
    with pytest.raises(SandboxError):
        check_sql(sql)


def test_literals_do_not_trigger_keywords():
    assert check_sql("SELECT 'drop; delete' AS x")


def test_sql_error_and_timeout():
    sb = Sandbox(make_biz())
    with pytest.raises(SandboxError):
        sb.run("SELECT nope FROM orders")
    with pytest.raises(SandboxError):
        sb.run("SELECT count(*) FROM range(1000000000) a, range(1000000000) b", timeout=0.5)


def test_no_file_access():
    sb = Sandbox(make_biz())
    with pytest.raises(SandboxError):
        sb.run("SELECT * FROM 'tests/test_sandbox.py'")
