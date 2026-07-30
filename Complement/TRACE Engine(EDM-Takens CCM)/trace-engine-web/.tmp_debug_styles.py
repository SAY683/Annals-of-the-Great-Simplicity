#!/usr/bin/env python3
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:3000/?nocache=1"

async def main():
    async with async_playwright() as p:
        chromium_path = r"C:\Users\SAY\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe"
        browser = await p.chromium.launch(headless=True, executable_path=chromium_path)
        page = await browser.new_page(viewport={"width": 1600, "height": 1200})
        page.on("console", lambda msg: print("[CONSOLE]", msg.type, msg.text))
        await page.goto(BASE_URL, wait_until="networkidle")
        await asyncio.sleep(3)

        # 运行 LIGHT 分析
        await page.evaluate("""
            document.getElementById('textInput').value = '算法推荐系统通过持续分析用户行为数据，精准推送用户感兴趣的内容。然而，这种个性化推送机制会在长期运行中导致信息茧房效应的形成。';
            document.getElementById('modeLight').checked = true;
            startAnalysis();
        """)
        await page.locator("#mainMatrixView").wait_for(state="visible", timeout=60000)
        await asyncio.sleep(2)

        # 检查 job_history 样式
        print("=== JOB HISTORY STYLES ===")
        job_info = await page.evaluate("""
            (() => {
                const card = document.querySelector('#jobHistoryTerminal .terminal-line.job-card');
                if (!card) return 'no job-card found';
                const preview = card.querySelector('.job-preview');
                const row = card.querySelector('.job-card-row');
                const cardStyle = window.getComputedStyle(card);
                const previewStyle = preview ? window.getComputedStyle(preview) : null;
                const rowStyle = row ? window.getComputedStyle(row) : null;
                return {
                    cardChildren: Array.from(card.children).map(c => c.className || c.tagName),
                    cardDisplay: cardStyle.display,
                    cardFlexWrap: cardStyle.flexWrap,
                    cardGap: cardStyle.gap,
                    cardAlignItems: cardStyle.alignItems,
                    rowDisplay: rowStyle ? rowStyle.display : null,
                    rowFlexWrap: rowStyle ? rowStyle.flexWrap : null,
                    previewDisplay: previewStyle ? previewStyle.display : null,
                    previewFlex: previewStyle ? previewStyle.flex : null,
                    previewOrder: previewStyle ? previewStyle.order : null,
                    previewWidth: previewStyle ? previewStyle.width : null,
                    previewMarginTop: previewStyle ? previewStyle.marginTop : null,
                    previewBoxSizing: previewStyle ? previewStyle.boxSizing : null,
                };
            })()
        """)
        print(job_info)

        # 检查 2D 网络状态
        print("\n=== 2D NETWORK STATE ===")
        await page.locator("#mainTopo2DToggle").click()
        await asyncio.sleep(2)
        net_info = await page.evaluate("""
            (() => {
                const canvas = document.getElementById('topology2DCanvas');
                if (!canvas) return 'canvas missing';
                const s = topology2DStates.get(canvas);
                if (!s) return 'no state';
                return {
                    W: s.W, H: s.H, nodes: s.nodes.length, edges: s.edges.length,
                    firstNode: s.nodes[0] ? {
                        id: s.nodes[0].id,
                        x: s.nodes[0].x, y: s.nodes[0].y,
                        vx: s.nodes[0].vx, vy: s.nodes[0].vy,
                        radius: s.nodes[0].radius,
                        hasX: 'x' in s.nodes[0], keys: Object.keys(s.nodes[0])
                    } : null,
                    secondNode: s.nodes[1] ? { id: s.nodes[1].id, x: s.nodes[1].x, y: s.nodes[1].y } : null,
                    edge0: s.edges[0] ? {
                        sourceId: s.edges[0].source.id,
                        targetId: s.edges[0].target.id,
                        sourceX: s.edges[0].source.x,
                        targetX: s.edges[0].target.x
                    } : null
                };
            })()
        """)
        print(net_info)

        # 直接测试 initPositions2D
        print("\n=== INIT POSITIONS TEST ===")
        init_test = await page.evaluate("""
            (() => {
                const testNodes = [{id:'a', freq:1}, {id:'b', freq:1}, {id:'c', freq:2}];
                initPositions2D(testNodes, [], 200, 100);
                return {
                    n0: testNodes[0],
                    n1: testNodes[1],
                    n2: testNodes[2]
                };
            })()
        """)
        print(init_test)

        # 使用真实 r 对象模拟 init2D
        print("\n=== REAL INIT2D TEST ===")
        real_test = await page.evaluate("""
            (() => {
                const r = lastResult || window.lastAnalysisResult;
                if (!r) return 'no lastResult';
                const allConcepts = (r.concepts || []).slice(0, 64);
                const freq = r.concept_frequencies || {};
                const nodes = allConcepts.map((c, i) => ({ id: c, index: i, freq: freq[c] || 1 }));
                const edges = [];
                const matrix = r.adjacency_matrix;
                if (matrix && matrix.length === allConcepts.length) {
                    for (let i = 0; i < allConcepts.length; i++) {
                        for (let j = 0; j < allConcepts.length; j++) {
                            if (i === j) continue;
                            const v = Number(matrix[i][j]);
                            if (!isNaN(v) && Math.abs(v) > 0.01) {
                                edges.push({ source: nodes[i], target: nodes[j], strength: v });
                            }
                        }
                    }
                }
                initPositions2D(nodes, edges, 1514, 420);
                return {
                    conceptCount: allConcepts.length,
                    edgeCount: edges.length,
                    n0: nodes[0],
                    n1: nodes[1],
                    matrixType: typeof matrix,
                    matrixLen: matrix ? matrix.length : 0,
                    sampleMatrix: matrix && matrix[0] ? matrix[0].slice(0,3) : null
                };
            })()
        """)
        print(real_test)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
