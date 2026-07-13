#!/usr/bin/env python3
"""
trace-engine-web API 端到端测试
================================
用法:
    python tests/test_api.py [base_url]

默认测试 http://localhost:3000，可通过参数覆盖，如：
    python tests/test_api.py http://localhost:3003

测试覆盖:
1. 健康检查 /api/health
2. 版本/识别 /api/version
3. 参数 schema /api/schema
4. 运行时指标 /api/metrics
5. 参数预设 /api/presets
6. 同步文本分析 /api/analyze-text (LIGHT)
7. 同步文本分析 /api/analyze-text (DEEP)
8. SSE 流式分析 /api/analyze-stream
9. 单任务查询 /api/jobs/:id
10. 任务历史 /api/jobs
11. 输入校验（空文本、非法参数）
12. 结果/报告下载 /api/result/:id, /api/report/:id
"""

import http.client
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

DEFAULT_BASE = "http://localhost:3000"


def parse_base(base: str):
    p = urllib.parse.urlparse(base)
    return p.hostname or "localhost", p.port or 80


class Client:
    def __init__(self, base: str):
        self.host, self.port = parse_base(base)
        self.conn = http.client.HTTPConnection(self.host, self.port, timeout=300)

    def request(self, method: str, path: str, body=None, headers=None):
        h = headers or {}
        if isinstance(body, dict):
            body = json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        self.conn.request(method, path, body=body, headers=h)
        resp = self.conn.getresponse()
        data = resp.read().decode("utf-8")
        try:
            return resp.status, json.loads(data)
        except Exception:
            return resp.status, data

    def sse_request(self, method: str, path: str, body=None):
        h = {"Accept": "text/event-stream"}
        if isinstance(body, dict):
            body = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        self.conn.request(method, path, body=body, headers=h)
        resp = self.conn.getresponse()
        events = []
        buf = b""
        while True:
            chunk = resp.read(2048)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                block, buf = buf.split(b"\n\n", 1)
                evt, dat = None, None
                for line in block.decode("utf-8").split("\n"):
                    if line.startswith("event:"):
                        evt = line[6:].strip()
                    elif line.startswith("data:"):
                        dat = line[5:].strip()
                if evt and dat:
                    try:
                        events.append((evt, json.loads(dat)))
                    except Exception:
                        events.append((evt, dat))
        return resp.status, events


def load_sample(name: str = "sample_input.txt") -> str:
    root = Path(__file__).resolve().parent.parent
    path = root / name
    if not path.exists():
        raise FileNotFoundError(f"未找到 {path}")
    return path.read_text(encoding="utf-8")


def assert_ok(status: int, data, msg: str):
    ok = status == 200 and isinstance(data, dict) and data.get("success") is True
    if not ok:
        raise AssertionError(f"{msg} 失败: status={status}, data={data!r}")
    print(f"  [OK] {msg}")


def run_all(base: str):
    print(f"测试目标: {base}")
    client = Client(base)

    # 1. health
    status, data = client.request("GET", "/api/health")
    assert_ok(status, data, "健康检查")
    if not data.get("skillReady"):
        raise AssertionError("Skill 目录未就绪")

    # 2. version
    status, data = client.request("GET", "/api/version")
    assert_ok(status, data, "版本识别")

    # 3. schema
    status, data = client.request("GET", "/api/schema")
    assert_ok(status, data, "参数 Schema")
    if "threshold" not in data.get("schema", {}):
        raise AssertionError("schema 缺少 threshold")

    # 4. metrics
    status, data = client.request("GET", "/api/metrics")
    assert_ok(status, data, "运行时指标")

    # 5. presets
    status, data = client.request("GET", "/api/presets")
    assert_ok(status, data, "参数预设")
    if "default" not in data.get("presets", {}):
        raise AssertionError("presets 缺少 default")

    # 6. analyze-text light
    text = load_sample()
    status, data = client.request("POST", "/api/analyze-text", {
        "text": text,
        "mode": "light",
        "config": {"threshold": 0.5, "window_size": 8, "max_concepts": 12},
    })
    assert_ok(status, data, "同步分析 LIGHT")
    result = data["data"]["result"]
    if not result.get("concepts"):
        raise AssertionError("LIGHT 模式未返回概念")
    job_id = data["data"]["id"]

    # 7. single job
    status, data = client.request("GET", f"/api/jobs/{job_id}")
    assert_ok(status, data, "单任务查询")

    # 8. result / report
    status, _ = client.request("GET", f"/api/result/{job_id}")
    if status != 200:
        raise AssertionError("结果文件下载失败")
    print("  [OK] 结果文件下载")

    # 9. analyze-text deep
    status, data = client.request("POST", "/api/analyze-text", {
        "text": text,
        "mode": "deep",
        "config": {"threshold": 0.5, "window_size": 8, "max_concepts": 12},
    })
    assert_ok(status, data, "同步分析 DEEP")
    result = data["data"]["result"]
    if not result.get("six_warriors"):
        raise AssertionError("DEEP 模式未返回六战士诊断")
    print(f"  [OK] DEEP 六战士诊断: {list(result['six_warriors'].keys())}")

    # 10. SSE stream
    status, events = client.sse_request("POST", "/api/analyze-stream", {
        "text": text[:500],
        "mode": "light",
        "id": f"test-sse-{int(time.time())}",
    })
    if status != 200:
        raise AssertionError(f"SSE 流状态异常: {status}")
    event_types = [e[0] for e in events]
    if "result" not in event_types:
        raise AssertionError(f"SSE 未收到 result 事件: {event_types}")
    print(f"  [OK] SSE 流式分析 (events: {event_types})")

    # 11. input validation
    status, data = client.request("POST", "/api/analyze-text", {"text": "", "mode": "light"})
    if status != 400 or data.get("code") != "EMPTY_TEXT":
        raise AssertionError(f"空文本校验异常: {status} {data}")
    print("  [OK] 空文本校验")

    status, data = client.request("POST", "/api/analyze-text", {
        "text": text,
        "mode": "deep",
        "config": {"threshold": 999},
    })
    if status != 400 or data.get("code") != "INVALID_PARAM":
        raise AssertionError(f"非法参数校验异常: {status} {data}")
    print("  [OK] 非法参数校验")

    # 12. jobs list
    status, data = client.request("GET", "/api/jobs")
    assert_ok(status, data, "任务历史列表")

    print("\n全部测试通过")


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TRACE_WEB_BASE", DEFAULT_BASE)
    try:
        run_all(base)
    except Exception as e:
        print(f"\n测试失败: {e}")
        sys.exit(1)
