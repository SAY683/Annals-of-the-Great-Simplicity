#!/usr/bin/env python3
"""
浏览器端验证脚本：使用 Playwright 截图验证前端修复。
"""
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:3000/?nocache=1"
OUT_DIR = Path(__file__).resolve().parent / "screenshots" / "round2"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def copy_latest_temp(prefix: str, dest: Path):
    """从系统临时目录复制浏览器代理生成的截图（如有）。"""
    tmp = Path(tempfile.gettempdir()) / "trae" / "screenshots"
    if not tmp.exists():
        return
    for f in sorted(tmp.glob(f"{prefix}*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            shutil.copy2(f, dest)
            print(f"copied temp {f} -> {dest}")
        except Exception:
            pass
        return


def find_chromium():
    """自动探测 Playwright 安装的 Chromium；失败则返回 None 让 Playwright 自行查找。"""
    local_appdata = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    base = Path(local_appdata) / 'ms-playwright'
    if base.exists():
        for d in sorted(base.glob('chromium-*'), key=lambda p: p.stat().st_mtime, reverse=True):
            exe = d / 'chrome-win64' / 'chrome.exe'
            if exe.exists():
                return str(exe)
            exe = d / 'chrome.exe'
            if exe.exists():
                return str(exe)
    return None


async def main():
    async with async_playwright() as p:
        chromium_path = find_chromium()
        launch_kwargs = {'headless': True}
        if chromium_path:
            launch_kwargs['executable_path'] = chromium_path
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(viewport={"width": 1600, "height": 1200})
        # 禁用缓存，确保加载最新 CSS/JS
        await context.set_extra_http_headers({"Cache-Control": "no-cache"})
        page = await context.new_page()

        # 捕获控制台错误与日志
        console_logs = []
        failed_requests = []
        page.on('console', lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on('pageerror', lambda err: console_logs.append(f"[pageerror] {err}"))
        page.on('requestfailed', lambda req: failed_requests.append(f"[requestfailed] {req.method} {req.url} -> {req.failure_error_text}"))
        page.on('response', lambda res: failed_requests.append(f"[http404] {res.request.method} {res.url}") if res.status == 404 else None)

        # 1. 打开页面并等待自动加载结果
        print(f"navigate to {BASE_URL}")
        await page.goto(BASE_URL, wait_until="networkidle")
        await asyncio.sleep(5)
        # DEBUG: 列出所有 404 资源
        try:
            entries = await page.evaluate("""
                () => performance.getEntriesByType('resource')
                    .filter(r => r.responseStatus === 404 || r.responseStatus === 0)
                    .map(r => ({url: r.name, status: r.responseStatus, type: r.initiatorType}))
            """)
            if entries:
                print("DEBUG 404 resources:", entries)
        except Exception as e:
            print("DEBUG entries error:", e)
        await page.screenshot(path=str(OUT_DIR / "p1_home.png"), full_page=False)
        print("saved p1_home.png")

        # 2. 如果没有自动加载结果，手动运行 LIGHT 分析
        has_result = False
        try:
            has_result = await page.locator("#mainMatrixView").is_visible(timeout=3000)
        except Exception:
            has_result = False
        if not has_result:
            print("no auto-loaded result, running LIGHT via JS...")
            # 调用前端 startAnalysis 走完整 SSE 流程
            await page.evaluate("""
                document.getElementById('textInput').value = `算法推荐系统通过持续分析用户行为数据，精准推送用户感兴趣的内容。然而，这种个性化推送机制会在长期运行中导致信息茧房效应的形成。信息茧房使得用户长期只接触单一观点，从而加剧了观点极化的趋势。观点极化进一步侵蚀了社会共识的基础。当社会共识瓦解后，公共讨论空间也随之萎缩。公共讨论空间的萎缩又会削弱社会监督功能，社会监督功能的弱化反过来降低算法平台的问责压力。算法平台问责压力的降低，使得算法透明度改革难以推进。算法透明度改革的迟滞进一步固化信息茧房，从而形成一条完整的因果反馈回路。`;
                document.getElementById('modeLight').checked = true;
                startAnalysis();
            """)
            # 等待分析完成（结果面板出现）
            try:
                await page.locator("#mainMatrixView").wait_for(state="visible", timeout=60000)
                await asyncio.sleep(2)
            except Exception as e:
                print("WARN: 等待结果面板超时或分析失败:", e)
                # 继续后续截图，以便排查日志

        # 3. 滚动到矩阵并截图
        try:
            await page.locator("#mainMatrixView").scroll_into_view_if_needed()
            await asyncio.sleep(1)
        except Exception as e:
            print("WARN: 矩阵面板未显示，跳过矩阵截图:", e)
        await page.screenshot(path=str(OUT_DIR / "p2_matrix.png"), full_page=False)
        print("saved p2_matrix.png")

        # 4. 点击 2D 网络按钮并截图
        btn_2d = page.locator("#mainTopo2DToggle")
        try:
            if await btn_2d.is_visible(timeout=3000):
                await btn_2d.click()
                await asyncio.sleep(2)
                await page.screenshot(path=str(OUT_DIR / "p3_2d_network.png"), full_page=False)
                print("saved p3_2d_network.png")
                # DEBUG: inspect topology2DStates
                try:
                    debug_info = await page.evaluate("""
                        (() => {
                            const canvas = document.getElementById('topology2DCanvas');
                            if (!canvas) return 'canvas missing';
                            const s = topology2DStates.get(canvas);
                            if (!s) return 'no state';
                            return JSON.stringify({
                                W: s.W, H: s.H, scale: s.scale, panX: s.panX, panY: s.panY,
                                nodes: s.nodes.length, edges: s.edges.length,
                                firstNode: s.nodes[0] ? {id: s.nodes[0].id, x: s.nodes[0].x, y: s.nodes[0].y, r: s.nodes[0].radius} : null,
                                canvasW: canvas.width, canvasH: canvas.height,
                                wrapRect: (r => ({w:r.width,h:r.height})) (document.getElementById('topology2DWrap').getBoundingClientRect())
                            });
                        })()
                    """)
                    print("DEBUG 2D state:", debug_info)
                except Exception as e:
                    print("DEBUG evaluate error:", e)
        except Exception as e:
            print("2D button click error:", e)

        # 5. 点击 3D 拓扑按钮
        btn_3d = page.locator("#mainTopoToggle")
        try:
            visible_3d = await btn_3d.is_visible(timeout=3000)
        except Exception:
            visible_3d = False
        if visible_3d:
            await btn_3d.click()
            await asyncio.sleep(2)
            await page.screenshot(path=str(OUT_DIR / "p4_3d.png"), full_page=False)
            print("saved p4_3d.png")

            # 点击 3D canvas 中心区域（节点通常在中心附近）
            canvas = page.locator("#topologyCanvas")
            box = await canvas.bounding_box()
            if box:
                cx = box["x"] + box["width"] * 0.5
                cy = box["y"] + box["height"] * 0.5
                await page.mouse.click(cx, cy)
                await asyncio.sleep(2)
                await page.screenshot(path=str(OUT_DIR / "p5_2d_after_click.png"), full_page=False)
                print("saved p5_2d_after_click.png")

        # 6. job_history 面板
        await page.locator("#jobHistoryTerminal").scroll_into_view_if_needed()
        await asyncio.sleep(1)
        # DEBUG: 检查首个 job-preview 的计算样式，确认 CSS 是否生效
        try:
            style_info = await page.evaluate("""
                (() => {
                    const row = document.querySelector('#jobHistoryTerminal .job-card');
                    const rowInner = document.querySelector('#jobHistoryTerminal .job-card .job-card-row');
                    const preview = document.querySelector('#jobHistoryTerminal .job-card .job-preview');
                    const link = document.querySelector('link[href*="main.css"]');
                    return JSON.stringify({
                        row_display: row ? getComputedStyle(row).display : null,
                        row_flexWrap: row ? getComputedStyle(row).flexWrap : null,
                        rowInner_width: rowInner ? getComputedStyle(rowInner).width : null,
                        rowInner_flexBasis: rowInner ? getComputedStyle(rowInner).flexBasis : null,
                        preview_display: preview ? getComputedStyle(preview).display : null,
                        preview_width: preview ? getComputedStyle(preview).width : null,
                        preview_flexBasis: preview ? getComputedStyle(preview).flexBasis : null,
                        preview_order: preview ? getComputedStyle(preview).order : null,
                        row_rect: row ? row.getBoundingClientRect() : null,
                        rowInner_rect: rowInner ? rowInner.getBoundingClientRect() : null,
                        preview_rect: preview ? preview.getBoundingClientRect() : null,
                        css_href: link ? link.href : null,
                    });
                })()
            """)
            print("DEBUG job-preview style:", style_info)
        except Exception as e:
            print("DEBUG style error:", e)
        await page.screenshot(path=str(OUT_DIR / "p6_job_history.png"), full_page=False)
        print("saved p6_job_history.png")

        # 7. realtime_log 面板
        await page.locator("#terminal").scroll_into_view_if_needed()
        await asyncio.sleep(1)
        await page.screenshot(path=str(OUT_DIR / "p7_log.png"), full_page=False)
        print("saved p7_log.png")

        await browser.close()
        if failed_requests:
            print("--- FAILED REQUESTS ---")
            for line in failed_requests[-40:]:
                print(line)
        if console_logs:
            print("--- CONSOLE LOGS ---")
            for line in console_logs[-80:]:
                print(line)
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
