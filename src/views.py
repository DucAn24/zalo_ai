"""SQL views over the canonical tables: valid orders / valid lines according to the rulebook's
revenue definition (not cancelled, not returned; shipping orders still count)."""
from __future__ import annotations

from .canon import Business


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def build_views(biz: Business, non_item_names: list[str] | None = None) -> list[str]:
    t = biz.tables
    stmts: list[str] = []
    non_item = non_item_names or []
    is_item = "TRUE" if not non_item else f"(l.product_name IS NULL OR lower(l.product_name) NOT IN ({', '.join(_q(n.lower()) for n in non_item)}))"

    orders = t.get("orders")
    lines = t.get("lines")
    products = t.get("products")
    ocols = set(orders.columns) if orders is not None else set()
    lcols = set(lines.columns) if lines is not None else set()

    if orders is not None:
        stmts.append(
            "CREATE VIEW valid_orders AS SELECT *, COALESCE(items_amount, goods_amount) AS revenue FROM orders "
            "WHERE COALESCE(status, 'hoan_thanh') NOT IN ('huy', 'tra_hang') AND NOT COALESCE(has_return, FALSE)")

    group_join = ""
    group_col = "NULL AS group_name"
    if products is not None and "group_name" in products.columns and products["group_name"].notna().any():
        if lines is not None and "product_id" in lcols and lines["product_id"].notna().any() \
                and products["product_id"].notna().any():
            stmts.append("CREATE VIEW _prod AS SELECT * FROM products QUALIFY row_number() OVER (PARTITION BY product_id ORDER BY product_name) = 1")
            group_join, group_col = "LEFT JOIN _prod p ON p.product_id = l.product_id", "p.group_name AS group_name"
        else:
            stmts.append("CREATE VIEW _prod AS SELECT * FROM products QUALIFY row_number() OVER (PARTITION BY product_name ORDER BY product_id) = 1")
            group_join, group_col = "LEFT JOIN _prod p ON p.product_name = l.product_name", "p.group_name AS group_name"

    if lines is not None:
        lsel = [f"l.{c}" for c in ("order_id", "line_no", "product_id", "product_name", "base_unit", "unit", "qty",
                                   "qty_base", "unit_price", "line_discount", "line_amount", "cost_unit") if c in lcols]
        if orders is not None and "order_id" in lcols and lines["order_id"].notna().any():
            osel = [f"o.{c} AS {c}" for c in ("order_date", "order_ts", "customer_key", "customer_display", "is_walkin",
                                               "customer_group", "payment_method", "channel", "employee_id")
                    if c in ocols and orders[c].notna().any()]
            if "order_date" not in [x.split(" AS ")[-1] for x in osel]:
                osel.append("l.order_date AS order_date")
            sql = (f"CREATE VIEW valid_lines AS SELECT {', '.join(lsel + osel)}, {group_col}, {is_item} AS is_item "
                   f"FROM lines l JOIN valid_orders o ON o.order_id = l.order_id {group_join}")
        else:
            extra = [f"l.{c}" for c in ("order_date", "order_time", "customer_name") if c in lcols]
            sql = (f"CREATE VIEW valid_lines AS SELECT {', '.join(lsel + extra)}, {group_col}, {is_item} AS is_item "
                   f"FROM lines l {group_join} WHERE COALESCE(l.status, 'hoan_thanh') NOT IN ('huy', 'tra_hang') "
                   f"AND NOT COALESCE(l.is_return_line, FALSE)")
        stmts.append(sql)
    return stmts
