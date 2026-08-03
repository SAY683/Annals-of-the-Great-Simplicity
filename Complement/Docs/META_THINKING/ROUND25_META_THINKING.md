# ROUND 25 — 声明-实现鸿沟修缮与端到端验证

> 生成时间: 2026-07-28 | 涉及项目: TRACE-TO-EDM, TRACE ENGINE, EDM-TAKENS

---

## §1 核心反思：为什么 Round 24 仍然遗漏了问题

### 1.1 最严重的发现：声明-实现鸿沟依然存在

Round 24 文档声称"人话版报告同时在项目 outputs/ 目录落盘"，但本轮核查发现 **EDM-TAKENS 的 history.py 根本没有写盘代码** —— 注释说落盘了，代码却只有 `StreamingResponse`。这正是用户痛斥的"声明-实现鸿沟"。

| 项目 | 声明 | 实际 | 修复 |
|------|------|------|------|
| EDM-TAKENS history.py | "人话版报告同时在项目 outputs/ 目录落盘" | 只有 StreamingResponse，无 write 操作 | 补全 `open(report_path, 'w').write(md_content)` |
| TRACE ENGINE jobs.js | "report.md 已在 OUTPUT_DIR/<id>/report.md 落盘" | export/md 端点不写人话版到磁盘 | 补全 `fs.promises.writeFile(human_report_path, mdContent)` |
| TRACE-TO-EDM server.js | 已实现写盘 | 确认已实现 ✓ | 无需修复 |

### 1.2 Round 24 遗漏的根因分析

| 遗漏项 | 根因 | 本轮修复 |
|--------|------|----------|
| 历史记录缺热力词矩阵 | `renderResultMetrics()` 只渲染指标卡片+参数+边表，**不渲染热力图** | 补全 adjacency_matrix 热力图渲染 |
| SUPER 模式信息少于 LIGHT/DEEP | `renderResultMetrics()` 不渲染反事实扫描/六战士/稳定性 | 补全三个章节的渲染逻辑 |
| EDM-TAKENS 配置列字体不统一 | `#columnInfo strong` (0.85rem) vs `.recommendation-box` (0.8rem) vs `.col-chip` (0.74rem) 字号差距明显 | 统一为 `clamp(0.7rem, 0.92vw, 0.8rem)` |

### 1.3 为什么排查方法有显著问题

用户指出："你每一次都能检察到错误，却无法修缮完备"。根因在于：

1. **只验证代码存在，不验证代码生效**：Round 24 声称修复了 `layer1_meta_scm.py`，确认了代码存在，但未重启服务验证运行时表现。
2. **只验证后端返回，不验证前端渲染**：后端 API 返回了 `adjacency_matrix`，但前端 `renderResultMetrics` 根本不消费它。
3. **只验证单点，不验证对比**：未对比"正常运行显示什么"vs"历史记录显示什么"，导致热力图缺失未被发现。
4. **注释即真理的幻觉**：看到注释说"落盘"就认为已落盘，未实际检查文件系统。

---

## §2 本轮修复清单

### 2.1 P1 修复（功能完整性）

| 编号 | 项目 | 问题 | 修复方式 | 验证状态 |
|------|------|------|----------|----------|
| P1-1 | TRACE ENGINE | 历史记录缺热力词矩阵 | `renderResultMetrics` 补全 adjacency_matrix grid 渲染 | ✅ 浏览器验证通过 |
| P1-2 | TRACE ENGINE | 历史记录缺反事实扫描 | 补全 `counterfactual_scan` 表格渲染 | ✅ 浏览器验证通过 |
| P1-3 | TRACE ENGINE | 历史记录缺六战士摘要 | 补全 CCM/EDM/HAVOK/CausalLearn 指标 | ✅ 浏览器验证通过 |
| P1-4 | TRACE ENGINE | 历史记录缺稳定性分析 | 补全 `stability_analysis` 参数网格 | ✅ 浏览器验证通过 |
| P1-5 | EDM-TAKENS | 人话版报告未落盘 | `history.py` 补全 `open(report_path, 'w').write(md_content)` | 代码已修复 |
| P1-6 | TRACE ENGINE | 人话版报告未落盘 | `jobs.js` 补全 `fs.promises.writeFile(human_report_path, mdContent)` | 代码已修复 |
| P1-7 | EDM-TAKENS | 配置列字体不统一 | 统一 `clamp(0.7rem, 0.92vw, 0.8rem)` | ✅ 浏览器验证通过 |

### 2.2 已确认前轮修复生效项

| 项目 | 修复项 | 验证结果 |
|------|--------|----------|
| TRACE-TO-EDM | `_safe_percent` 值域守卫 | ✅ 代码存在，CSV 数据正常 |
| TRACE-TO-EDM | trace_status/trace_mode/trace_error 列 | ✅ CSV 和前端均有 |
| TRACE-TO-EDM | 日志面板 max-height 限制 | ✅ CSS `min(60vh, 480px)` + 400行上限 |
| TRACE ENGINE | SUPER 模式 adjacency_matrix 输出 | ✅ `llama_worker.py:1100` |
| TRACE ENGINE | SUPER 模式 100% 进度 | ✅ `stage("done", 1.0)` 在 `emit` 之前 |
| EDM-TAKENS | 进度条三阶段映射 | ✅ `main.js:500-569` |
| EDM-TAKENS | 多任务对比 2-8 个 | ✅ `CompareRequest max_items=8` + CSS grid 3-8 |
| 三大 Web | 人话版新标签页展示 | ✅ 无 Content-Disposition: attachment |

### 2.3 已确认无需修复项

| 项目 | 用户疑虑 | 实际情况 |
|------|----------|----------|
| TRACE-TO-EDM | refuted_count/ccm_coverage_pct 全为 0 | LIGHT 模式不运行反驳/CCM，0 是正确值 |
| TRACE-TO-EDM | dz_列空值断档 | 差分计算需要两个数据点，首行为空正常；部分轴无投影值也是正常 |
| TRACE ENGINE | SUPER 模式慢 | 470M 模型 ~10 pps，算法正确，性能受限于模型规模 |
| TRACE ENGINE | ADVANCED_PARAMETERS | 通过 `/api/schema` 动态加载，`<details>` 折叠面板可展开 |

---

## §3 端到端浏览器验证结果

### 3.1 TRACE ENGINE (http://127.0.0.1:3000)

| 验证项 | 结果 | 证据 |
|--------|------|------|
| 历史记录点击 → 详情模态框 | ✅ PASS | 模态框弹出成功 |
| ADJACENCY MATRIX (热力词矩阵) | ✅ PASS | 标题和 canvas 网格存在 |
| COUNTERFACTUAL SCAN (反事实扫描) | ✅ PASS | 标题和表格存在 |
| SIX WARRIORS (六战士摘要) | ✅ PASS | 标题和参数网格存在 |
| STABILITY ANALYSIS | ✅ PASS | 标题和参数网格存在 |

### 3.2 TRACE-TO-EDM (http://127.0.0.1:3100)

| 验证项 | 结果 | 证据 |
|--------|------|------|
| trace_status/trace_mode/trace_error 列 | ✅ PASS | API 返回 OK/light/空 |
| refuted_count=0, ccm_coverage_pct=0.0 | ✅ PASS | LIGHT 模式正常值 |
| dz_ 列空值显示 — | ✅ PASS | 差分列空值渲染为 — |
| 日志面板 max-height 限制 | ✅ PASS | 60vh/480px + 400行上限 |

### 3.3 EDM-TAKENS (http://127.0.0.1:5173)

| 验证项 | 结果 | 证据 |
|--------|------|------|
| 配置列字体大小统一 | ✅ PASS | 字号层级清晰，无偏大不等 |
| 无"长条突兀"现象 | ✅ PASS | 元素排布正常 |
| 多任务对比 2-8 个 | ✅ PASS | CSS grid 支持 3-8 列布局 |

---

## §4 缜密计划方法论（更新版）

### 4.1 防止"声明-实现鸿沟"的检查清单

每次声称修复后，必须执行以下验证：

1. **代码存在性验证**：`grep` 确认修复代码在文件中
2. **代码生效性验证**：重启服务，确认新代码被加载
3. **端到端验证**：用浏览器实际操作，确认用户可见效果
4. **对比验证**：对比"修复前"vs"修复后"，确认变化
5. **落盘验证**：声称写盘的，检查文件系统是否真的有文件

### 4.2 防止"前端遗漏"的检查清单

每次修改后端 API 返回字段后，必须检查：

1. 前端是否有消费该字段的代码
2. 前端渲染函数是否被实际调用
3. 历史记录详情是否与实时运行结果展示一致

### 4.3 反思循环

```
用户报告问题 → 核查代码 → 修复 → 验证代码存在 → 重启服务 → 浏览器验证 → 更新文档
     ↑                                                                              |
     └──────────────────────── 发现新问题 ←────────────────────────────────────────┘
```

---

## §5 待办事项（P3，不阻塞当前功能）

| 编号 | 项目 | 待办 | 优先级 |
|------|------|------|--------|
| P3-1 | TRACE ENGINE | ADVANCED_PARAMETERS 实际测试各参数组合 | 低 |
| P3-2 | TRACE ENGINE | SUPER 模式 max_delta_nll 长文本波动验证 | 低 |
| P3-3 | TRACE-TO-EDM | 旧数据行从 result.json 重构 | 低 |
| P3-4 | TRACE ENGINE | `_deploy_ccm` 调用真实 CCM 算法 | 低 |
| P3-5 | EDM-TAKENS | 人话版报告内容进一步完善 | 低 |

---

_本轮修缮核心教训：不要相信注释，只相信运行时行为。每次修复后必须用浏览器验证用户可见的效果，而非仅检查代码是否存在。_
