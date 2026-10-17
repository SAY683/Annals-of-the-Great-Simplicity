#!/usr/bin/env python3
"""Headless browser smoke test for the three Complement web applications.

This is a real browser test, not a mocked DOM check. It assumes the local
services are already running (see Complement/start_all.ps1).

Examples:
  python tools/browser_smoke.py
  python tools/browser_smoke.py --full
  python tools/browser_smoke.py --full --screenshots .tmp_browser_smoke

`--full` runs the TRACE LIGHT sample and the EDM `game_log.csv` analysis, then
checks the returned `column_mapping` for the historical deaths/damage swap.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except Exception as exc:  # pragma: no cover - environment check
    print(f"ERROR: playwright is required: {exc}")
    print("Install: python -m pip install playwright && python -m playwright install chromium")
    raise SystemExit(2)


DEFAULT_EDM = "http://127.0.0.1:5173/"
DEFAULT_TRACE = "http://127.0.0.1:3000/"
DEFAULT_BRIDGE = "http://127.0.0.1:3100/"


def preflight(url: str) -> None:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status >= 400:
            raise RuntimeError(f"{url} returned HTTP {response.status}")


def parse_sse_result(text: str) -> dict | None:
    result = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("type") == "result" and isinstance(message.get("data"), dict):
            result = message["data"]
    return result


def assert_no_console_errors(page, label: str, errors: list[str], warnings: list[str]) -> None:
    page.wait_for_timeout(500)
    if errors:
        raise AssertionError(f"{label} console/page errors:\n" + "\n".join(errors))
    if warnings:
        print(f"[{label}] console warnings ({len(warnings)}):")
        for warning in warnings[:5]:
            print(f"  - {warning}")


def run_edm(page, full: bool, timeout_ms: int, screenshot_dir: Path | None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: (
        errors.append(f"console.error: {msg.text}") if msg.type == "error"
        else warnings.append(msg.text) if msg.type == "warning" else None
    ))
    page.goto(DEFAULT_EDM, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_selector("#datasetSelect", timeout=timeout_ms)
    page.wait_for_function("document.querySelectorAll('#datasetSelect option').length > 0", timeout=timeout_ms)

    options = page.locator("#datasetSelect option").evaluate_all("els => els.map(e => e.value)")
    dataset = "game_log.csv" if "game_log.csv" in options else options[0]
    page.select_option("#datasetSelect", dataset)
    page.wait_for_selector("#runBtn:not([disabled])", timeout=timeout_ms)
    if screenshot_dir:
        page.screenshot(path=str(screenshot_dir / "edm-loaded.png"), full_page=True)

    result = None
    if full:
        stream_responses = []

        def on_response(response):
            if "/api/analyze/jobs/" in response.url and response.url.endswith("/stream"):
                stream_responses.append(response)

        page.on("response", on_response)
        page.click("#runBtn")
        page.wait_for_selector("#summary .success", timeout=max(timeout_ms, 420_000))
        page.wait_for_timeout(1000)
        for response in stream_responses:
            try:
                result = parse_sse_result(response.text())
            except Exception:
                continue
            if result is not None:
                break
        if result is None:
            # Some proxies buffer SSE bodies so Playwright cannot read them after
            # the response closes. The browser can still read the same immutable
            # task summary through the history API.
            latest = page.evaluate("""async () => {
                const history = await (await fetch('/api/history?limit=1')).json();
                if (!history.length) return null;
                const taskId = history[0].task_id;
                const detail = await (await fetch(`/api/history/${encodeURIComponent(taskId)}`)).json();
                return {task_id: taskId, summary: detail.summary};
            }""")
            if latest and latest.get("summary"):
                result = latest
        if result is None:
            raise AssertionError("EDM analysis finished but neither SSE nor history returned a result payload")
        summary = result.get("summary") or {}
        mapping = summary.get("column_mapping") or {}
        for alias in ("damage", "deaths"):
            original = mapping.get(alias)
            if original in ("damage", "deaths") and original != alias:
                raise AssertionError(f"EDM column mapping swapped: {mapping}")
        if screenshot_dir:
            page.screenshot(path=str(screenshot_dir / "edm-result.png"), full_page=True)

    assert_no_console_errors(page, "edm", errors, warnings)
    return {
        "dataset": dataset,
        "analysis_ran": full,
        "column_mapping": ((result or {}).get("summary") or {}).get("column_mapping", {}),
        "warnings": len(warnings),
    }


def run_trace(page, full: bool, timeout_ms: int, screenshot_dir: Path | None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: (
        errors.append(f"console.error: {msg.text}") if msg.type == "error"
        else warnings.append(msg.text) if msg.type == "warning" else None
    ))
    page.goto(DEFAULT_TRACE, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_selector("#loadSampleBtn", timeout=timeout_ms)
    metrics = {}
    if full:
        page.click("#loadSampleBtn")
        page.wait_for_function("document.getElementById('textInput').value.length > 0", timeout=timeout_ms)
        page.click("#analyzeBtn")
        page.wait_for_selector("#resultPanel:not(.hidden)", timeout=max(timeout_ms, 420_000))
        page.wait_for_function("document.getElementById('rATE').textContent.trim() !== '-'", timeout=timeout_ms)
        metrics = {
            "concepts": page.inner_text("#rConcepts").strip(),
            "edges": page.inner_text("#rEdges").strip(),
            "ate": page.inner_text("#rATE").strip(),
            "identifiable": page.inner_text("#rIdentifiable").strip(),
            "mode": page.inner_text("#rMode").strip(),
        }
        warning = page.inner_text("#dataSourceWarning")
        if "合成 SEM" not in warning:
            raise AssertionError("TRACE result does not expose the synthetic-SEM provenance warning")
        if screenshot_dir:
            page.screenshot(path=str(screenshot_dir / "trace-result.png"), full_page=True)
    assert_no_console_errors(page, "trace", errors, warnings)
    return {"analysis_ran": full, "metrics": metrics, "warnings": len(warnings)}


def run_bridge(page, timeout_ms: int, screenshot_dir: Path | None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: (
        errors.append(f"console.error: {msg.text}") if msg.type == "error"
        else warnings.append(msg.text) if msg.type == "warning" else None
    ))
    page.goto(DEFAULT_BRIDGE, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_selector("body", timeout=timeout_ms)
    if screenshot_dir:
        page.screenshot(path=str(screenshot_dir / "bridge-loaded.png"), full_page=True)
    assert_no_console_errors(page, "bridge", errors, warnings)
    return {"loaded": True, "warnings": len(warnings)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="run real TRACE LIGHT + EDM analyses")
    ap.add_argument("--timeout-seconds", type=int, default=60)
    ap.add_argument("--screenshots", type=Path, default=None)
    args = ap.parse_args()
    timeout_ms = args.timeout_seconds * 1000

    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)

    try:
        for url in (DEFAULT_EDM, DEFAULT_TRACE, DEFAULT_BRIDGE):
            preflight(url)
    except Exception as e:
        print(f"ERROR: local service not ready: {e}")
        print("Start services first: powershell -NoProfile -ExecutionPolicy Bypass -File Complement/start_all.ps1")
        return 2

    report = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        try:
            report["edm"] = run_edm(context.new_page(), args.full, timeout_ms, args.screenshots)
            report["trace"] = run_trace(context.new_page(), args.full, timeout_ms, args.screenshots)
            report["bridge"] = run_bridge(context.new_page(), timeout_ms, args.screenshots)
        finally:
            context.close()
            browser.close()

    print(json.dumps({"ok": True, "full": args.full, "results": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)