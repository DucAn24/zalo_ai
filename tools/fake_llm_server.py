"""A tiny OpenAI-compatible server that answers a few question templates with canned SQL.

It exists only to test the pipeline plumbing (HTTP client, parsing, periods, sandbox, retry, logging,
scoring) without a GPU. It is NOT a model: unknown questions get `TYPE: unanswerable`.

    python tools/fake_llm_server.py --port 8099 [--flaky 0.1]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PERIODS = [
    (r"thang (\d{1,2})(?:/| nam )(\d{4})", lambda m: f"month:{m.group(2)}-{int(m.group(1))}"),
    (r"quy (\d)(?:/| nam )(\d{4})", lambda m: f"quarter:{m.group(2)}-{m.group(1)}"),
    (r"(\d+) ngay gan nhat", lambda m: f"last_n_days:{m.group(1)}"),
    (r"\b(hom nay|hnay|bua nay)\b", lambda m: "today"),
    (r"\b(hom qua|hqua|bua qua)\b", lambda m: "yesterday"),
    (r"tuan (truoc|roi|trc)", lambda m: "last_week"),
    (r"tuan nay", lambda m: "this_week"),
    (r"thang nay", lambda m: "this_month"),
    (r"thang (truoc|roi|trc)", lambda m: "last_month"),
]
FILLER = set("""cho toi minh biet hoi doanh thu dthu tong cong cua hang ban duoc dc bao nhieu bn bnhiu nhiu tien la trong
ha z vay nhi a ta xem giup gium coi check the nao do e oi ve thu mang so luong ra hok khong k ko chu hen nhe nha s o tren tai
mot ngay nay qua hom hnay hqua bua tuan truoc roi trc thang nam tu dau toi het den gan nhat ky co bill don hoa may huy bi
ti le ty phan tram""".split())


def strip(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"\s+", " ", s).strip()


def answer_for(question: str, has_lines: bool, garbage_first: bool) -> str:
    p = strip(question)
    found = [f(m) for pat, f in PERIODS for m in re.finditer(pat, p)]
    rest = p
    for pat, _ in PERIODS:
        rest = re.sub(pat, " ", rest)
    only_filler = all(t in FILLER or t.isdigit() for t in re.findall(r"[a-z]+|\d+", rest.replace("%", " ")))
    if len(found) != 1 or not only_filler:
        return "TYPE: unanswerable\nREASON: mẫu câu không được fake server hỗ trợ."
    per = found[0]
    head = lambda t: f"TYPE: {t}\nPERIODS: P1 = {per}\n"
    if garbage_first:
        return "Tôi nghĩ doanh thu là khoảng 100 triệu."
    if re.search(r"(ti le|ty le|phan tram|%).*huy|huy.*(ti le|ty le|phan tram|%)", p):
        return head("percent") + ("SQL:\nSELECT 100.0 * SUM(CASE WHEN status = 'huy' THEN 1 ELSE 0 END) / COUNT(*) "
                                   "FROM orders WHERE {P1:order_date}")
    if re.search(r"don.*huy|huy.*don", p):
        return head("number") + "SQL:\nSELECT COUNT(*) FROM orders WHERE status = 'huy' AND {P1:order_date}"
    if re.search(r"(bao nhieu|may|bn|bnhiu|so) (don|bill|hoa don)", p) and "tien" not in p:
        return head("number") + "SQL:\nSELECT COUNT(*) FROM valid_orders WHERE {P1:order_date}"
    if has_lines:
        return head("number") + "SQL:\nSELECT COALESCE(SUM(line_amount), 0) FROM valid_lines WHERE {P1:order_date}"
    return head("number") + "SQL:\nSELECT COALESCE(SUM(revenue), 0) FROM valid_orders WHERE {P1:order_date}"


class Handler(BaseHTTPRequestHandler):
    flaky = 0.0

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._send({"data": [{"id": "fake"}]})
        else:
            self._send({}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        msgs = body["messages"]
        system = msgs[0]["content"]
        last = msgs[-1]["content"]
        m = re.search(r"CÂU HỎI:\s*(.*)", next((x["content"] for x in reversed(msgs)
                                                 if "CÂU HỎI:" in x["content"]), last))
        question = m.group(1) if m else ""
        is_fix = last.startswith("Lỗi:")
        h = int(hashlib.md5(question.encode()).hexdigest(), 16) % 1000 / 1000.0
        text = answer_for(question, "### valid_lines" in system, garbage_first=(h < self.flaky and not is_fix))
        n = int(body.get("n", 1))
        self._send({"choices": [{"message": {"role": "assistant", "content": text}} for _ in range(n)],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50}})


def serve(port: int = 0, flaky: float = 0.0) -> tuple[ThreadingHTTPServer, int]:
    Handler.flaky = flaky
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--flaky", type=float, default=0.1, help="fraction of questions answered with garbage first")
    a = ap.parse_args()
    srv, port = serve(a.port, a.flaky)
    print(f"fake LLM on http://127.0.0.1:{port}/v1", flush=True)
    threading.Event().wait()
