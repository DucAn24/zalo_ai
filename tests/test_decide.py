"""Answer threshold (rulebook penalty), suspect 'unanswerable' guard and the calibration table."""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eval import calibration  # noqa: E402
from src.config import answer_threshold, load_config  # noqa: E402
from src.rules import parse_rules  # noqa: E402
from src.sql_agent import existing_columns_named  # noqa: E402


def test_threshold_follows_rulebook_penalty_with_floor():
    cfg = load_config(overrides={"decide.min_confidence": 0.0})
    assert answer_threshold(cfg, None) == 0.5
    assert abs(answer_threshold(cfg, 2.0) - 2 / 3) < 1e-9
    cfg = load_config(overrides={"decide.min_confidence": 0.6})
    assert answer_threshold(cfg, 1.0) == 0.6                      # floor above break-even
    assert abs(answer_threshold(cfg, 3.0) - 0.75) < 1e-9          # break-even above floor


def test_rulebook_penalty_parsed():
    assert parse_rules("Đúng **+1**, sai **−1**, bỏ trống **0**.").penalty_hint == 1.0
    assert parse_rules("Đúng +1, sai −2, bỏ trống 0").penalty_hint == 2.0


def test_existing_columns_named_flags_only_real_columns():
    ctx = SimpleNamespace(any_nonnull={"order_ts", "customer_display", "revenue"}, tables={"valid_lines", "orders"})
    assert existing_columns_named("Không có cột `order_ts` trong bảng `valid_lines`", ctx) == ["order_ts"]
    assert existing_columns_named("thiếu customer_display, bảng valid_lines", ctx) == ["customer_display"]
    assert existing_columns_named("Dữ liệu không ghi giới tính khách; cột gender không có", ctx) == []
    assert existing_columns_named("", ctx) == []


def test_calibration_picks_threshold(capsys):
    items = [(1.0, True, "number")] * 6 + [(0.6, True, "number")] * 2 + [(0.6, False, "number")] * 2 \
        + [(0.2, False, "number")] * 5 + [(0.2, True, "unanswerable")]
    best = calibration(items, penalty=1.0)
    assert best[1] == 0.6                                         # 0.2-level answers lose points
    assert "calibration" in capsys.readouterr().out
