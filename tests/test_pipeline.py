"""End-to-end plumbing test on a tiny synthetic split with the fake OpenAI-compatible server."""
import datetime as dt
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from fake_llm_server import serve  # noqa: E402

from src.config import load_config  # noqa: E402
from src.main import find_split_dir, run_pipeline  # noqa: E402

RULEBOOK = """# Rulebook
## 1. Đơn hàng
| Luật | Mặc định |
|---|---|
| Đơn tính vào doanh thu | đơn **không huỷ** và **không trả hàng** |
Dòng **Phí phục vụ** không phải mặt hàng.
Đúng **+1**, sai **−1**, bỏ trống **0**.
"""


@pytest.fixture()
def split(tmp_path):
    root = tmp_path / "pub"
    biz = root / "data" / "biz_900"
    biz.mkdir(parents=True)
    rows = ["Mã hóa đơn,Ngày,Tên hàng,Số lượng,Đơn giá,Thành tiền,Trạng thái"]
    day = dt.date(2026, 1, 1)
    oid = 0
    expected = {"2026-01": 0, "2026-02": 0}
    for i in range(60):
        d = day + dt.timedelta(days=i)
        oid += 1
        status = "huỷ" if oid % 10 == 0 else "xong"
        amount = 10_000 * (1 + oid % 5)
        rows.append(f"ORD{oid:04d},{d.strftime('%d/%m/%Y')},Cà phê sữa,1,{amount},{amount},{status}")
        if status == "xong":
            expected[d.strftime("%Y-%m")] = expected.get(d.strftime("%Y-%m"), 0) + amount
    (biz / "ban_hang.csv").write_text("\n".join(rows), encoding="utf-8")
    (root / "rulebook.md").write_text(RULEBOOK, encoding="utf-8")
    (root / "calendar.csv").write_text(
        "date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday\n2026-01-01,4,13,11,2025,false,\n", encoding="utf-8")
    qs = [
        {"id": "q1", "business_id": "biz_900", "question": "doanh thu tháng 1/2026 là bn", "as_of_date": "2026-03-01"},
        {"id": "q2", "business_id": "biz_900", "question": "toongr dthu thangs 2/2026 bao nhiêu tieenf", "as_of_date": "2026-03-01"},
        {"id": "q3", "business_id": "biz_900", "question": "doanh thu tháng 6/2025 là bao nhiêu", "as_of_date": "2026-03-01"},
        {"id": "q4", "business_id": "biz_900", "question": "tháng 1/2026 có mấy đơn bị huỷ", "as_of_date": "2026-03-01"},
        {"id": "q5", "business_id": "biz_900", "question": "nhân viên nào dễ thương nhất", "as_of_date": "2026-03-01"},
    ]
    (root / "questions.jsonl").write_text("\n".join(json.dumps(q, ensure_ascii=False) for q in qs), encoding="utf-8")
    return root, expected


def test_find_split_dir(split, tmp_path):
    root, _ = split
    assert find_split_dir(str(root)) == str(root)
    assert find_split_dir(str(root.parent)) == str(root)


def test_pipeline_end_to_end(split, tmp_path):
    root, expected = split
    srv, port = serve(0, flaky=1.0)          # every first reply is garbage -> exercises the retry path
    try:
        cfg = load_config(overrides={"paths.cache_dir": str(tmp_path / "cache"), "run.workers": 2,
                                     "llm.base_url": f"http://127.0.0.1:{port}/v1", "llm.startup_wait_s": 10})
        out = tmp_path / "out"
        summary = run_pipeline(str(root), str(out), cfg=cfg)
    finally:
        srv.shutdown()
    sub = {json.loads(l)["id"]: json.loads(l) for l in open(out / "submission.jsonl", encoding="utf-8")}
    assert sub["q1"] == {"id": "q1", "type": "number", "answer": expected["2026-01"]}
    assert sub["q2"]["answer"] == expected["2026-02"]                      # telex repaired + retry
    assert sub["q3"]["type"] == "unanswerable"                              # period before the data
    assert sub["q4"]["type"] == "number" and sub["q4"]["answer"] == 3       # orders 10, 20, 30 are cancelled
    assert sub["q5"]["type"] == "unanswerable"
    logs = [json.loads(l) for l in open(out / "logs" / "logs.jsonl", encoding="utf-8")]
    assert len(logs) == 5 and all("elapsed_s" in x and "answer" in x for x in logs)
    assert any(len(s) > 1 for x in logs for s in x.get("attempts", []))     # a retry happened
    assert summary["questions"] == 5


def test_failed_business_is_remembered_and_resume_redoes_only_crashed(split, tmp_path, monkeypatch):
    import shutil
    from src.main import Runtime
    root, expected = split
    shutil.copytree(root / "data" / "biz_900", root / "data" / "biz_901")
    qs = [json.loads(l) for l in open(root / "questions.jsonl", encoding="utf-8") if l.strip()]
    extra = [{"id": f"b{i}", "business_id": "biz_901", "question": "doanh thu tháng 1/2026 là bn", "as_of_date": "2026-03-01"}
             for i in range(3)]
    (root / "questions.jsonl").write_text("\n".join(json.dumps(q, ensure_ascii=False) for q in qs + extra), encoding="utf-8")

    srv, port = serve(0)
    cfg = load_config(overrides={"paths.cache_dir": str(tmp_path / "cache"), "run.workers": 2,
                                 "llm.base_url": f"http://127.0.0.1:{port}/v1", "llm.startup_wait_s": 10})
    out = tmp_path / "out"
    real = Runtime._build_biz
    calls = {"bad": 0}

    def flaky(self, biz_id):
        if biz_id == "biz_901":
            calls["bad"] += 1
            raise ValueError("boom")
        return real(self, biz_id)

    try:
        monkeypatch.setattr(Runtime, "_build_biz", flaky)
        run_pipeline(str(root), str(out), cfg=cfg)
        assert calls["bad"] == 1                                    # remembered: not rebuilt for every question
        sub1 = {json.loads(l)["id"]: json.loads(l) for l in open(out / "submission.jsonl", encoding="utf-8")}
        assert all(sub1[f"b{i}"]["type"] == "abstain" for i in range(3))
        assert sub1["q1"]["answer"] == expected["2026-01"]
        monkeypatch.setattr(Runtime, "_build_biz", real)            # the bug is fixed; resume the run
        cfg2 = load_config(overrides={**{"paths.cache_dir": str(tmp_path / "cache"), "run.workers": 2,
                                         "llm.base_url": f"http://127.0.0.1:{port}/v1", "llm.startup_wait_s": 10},
                                      "run.resume": True})
        summary = run_pipeline(str(root), str(out), cfg=cfg2)
    finally:
        srv.shutdown()
    assert summary["questions"] == 3                                # only the crashed ones were redone
    lines = [json.loads(l) for l in open(out / "submission.jsonl", encoding="utf-8")]
    assert len(lines) == len({x["id"] for x in lines}) == 8         # one line per question
    final = {x["id"]: x for x in lines}
    assert all(final[f"b{i}"]["answer"] == expected["2026-01"] for i in range(3))
    assert final["q1"]["answer"] == expected["2026-01"]
