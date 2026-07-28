# ROUND 24 — 缜密排查与反思

> 生成时间: 2026-07-28 | 涉及项目: TRACE-TO-EDM, TRACE ENGINE, EDM-TAKENS

---

## §1 反思：为什么前几轮排查遗漏了这些问题

### 1.1 结构性缺陷分析

| 缺陷 | 表现 | 后果 | 对策 |
|------|------|------|------|
| **测试视角偏差** | 只验证 HTTP 200 + 字段存在，未验证数据内容质量 | ccm_coverage_pct=1.1e13 未被发现 | 加入值域守卫测试 |
| **未走完整用户路径** | 未实际触发 SUPER 完成、未对比三模式结果完整性 | SUPER 缺 adjacency_matrix 未发现 | 端到端全路径测试 |
| **"修复即完成"陷阱** | 标记 P0 修复后未回头验证下游数据 | signal_type=unknown（服务未重启） | 修复后必须验证运行时生效 |
| **未审视前端显示完整性** | 未对比"正常运行显示什么"vs"历史记录显示什么" | 历史记录缺热力图未发现 | 对比 LIGHT/DEEP/SUPER 三模式渲染 |
| **CSV 数据迁移盲区** | 添加新列后未验证旧数据行对齐 | 20 行错位数据污染下游 EDM | 列错位检测守卫 |

### 1.2 根因总结

前几轮的排查方法是 **"自下而上"** 的：先看代码，再测 API，最后（可能）看前端。
正确的方法应该是 **"自上而下"** 的：先看用户看到的界面，再追查数据流，最后审代码。

---

## §2 本轮修复清单

### 2.1 P0 修复（数据正确性）

| 编号 | 项目 | 问题 | 根因 | 修复 |
|------|------|------|------|------|
| P0-1 | TRACE-TO-EDM | ccm_coverage_pct 天文数字 (1.1e13) | 旧任务 result.json 存储 id() 内存地址 | `_safe_percent()` 值域守卫 [0,100] |
| P0-2 | TRACE-TO-EDM | dz_列空值断档 | CSV 表头更新后旧数据行未重写，列错位 | 删除 20 行错位数据 + 列错位检测守卫 |
| P0-3 | TRACE-TO-EDM | refuted_count/ccm_coverage_pct 恒为0 | 旧数据错位导致值被读取到错误列 | 同 P0-2 |
| P0-4 | TRACE-TO-EDM | trace_status/trace_mode/trace_error 缺失 | 旧数据行无这些列 | _load_existing 补 LEGACY 标记 |

### 2.2 P1 修复（功能完整性）

| 编号 | 项目 | 问题 | 修复 |
|------|------|------|------|
| P1-1 | TRACE ENGINE | SUPER 模式缺热力词矩阵 | llama_worker.py 补全 `adjacency_matrix` 字段 |
| P1-2 | TRACE ENGINE | SUPER 完成显示 98% 非 100% | `stage("done", 1.0)` 移到 `emit result` 之前 |
| P1-3 | TRACE-TO-EDM | 日志面板无限增长 | `max-height: min(60vh, 480px)` |
| P1-4 | EDM-TAKENS | 进度条恒卡 90% | 三阶段映射 (10-40% / 40-70% / 70-95%) |
| P1-5 | EDM-TAKENS | 多任务对比限制 2 个 | 放宽至 8 个，动态渲染对比网格 |
| P1-6 | EDM-TAKENS | 配置列字体长条突兀 | `clamp()` 响应式 + chip 样式 + word-break |
| P1-7 | EDM-TAKENS | 人话版粗糙未解析图谱 | 补全图谱解析 + 八正道审计章节 |

### 2.3 P2 修复（UX 一致性）

| 编号 | 项目 | 问题 | 修复 |
|------|------|------|------|
| P2-1 | 三大 Web | 人话版触发浏览器下载 | 改为新标签页直接展示 (text/markdown) |
| P2-2 | TRACE ENGINE | jobs.js 历史任务无语义徽章 | 补全 signal_type/refutations/CCM 徽章 |

---

## §3 数据流追踪审计

### 3.1 ccm_coverage_pct 数据流

```
six_warriors.py: CCM_coverage = eligible_concepts / total_unique_concepts
    ↓ (应为 [0, 1] 或 [0, 100])
result.json: six_warriors.ccm.metrics.CCM_coverage
    ↓ (旧任务可能存储了 id() 内存地址 ≈ 1e13)
layer1_meta_scm.py: _safe_float(raw) → 1.1e13  ← 无值域守卫
    ↓ (Round 24 修复)
layer1_meta_scm.py: _safe_percent(raw, lo=0, hi=100) → 0.0  ← 超出值域回退
    ↓
narrative_meta_trajectories.csv: ccm_coverage_pct = 0.0
    ↓
前端显示: 0.0% (正确)
```

### 3.2 CSV 列错位数据流

```
旧版本: header = [A, B, C, D] → data = [a1, b1, c1, d1]
    ↓ (新版本添加列 E 到 B 之后)
新版本: header = [A, E, B, C, D]
    ↓ (_load_existing 按新 header 读取旧 data)
DictReader: A=a1, E=b1(错!), B=c1(错!), C=d1(错!), D=缺失
    ↓
consensus_direction = "2151" (实际是 total_ms 的值)
    ↓ (Round 24 修复)
列错位检测: consensus_direction ∉ {positive,negative,ambiguous} → 拒绝加载
```

### 3.3 SUPER 模式进度条数据流

```
llama_worker.py:
  stage("finalize", 0.98)  ← 用户看到 98%
  emit(result)             ← 前端 setRunning(false), 隐藏进度条
  stage("done", 1.0)       ← 太晚! 进度条已隐藏
    ↓ (Round 24 修复)
  stage("finalize", 0.98)
  stage("done", 1.0)       ← 先发出 100%
  emit(result)             ← 前端显示 100% 后再隐藏
```

---

## §4 算法审计

### 4.1 SUPER 模式 ΔNLL 计算审计

```python
# llama_worker.py:748-775
nll_n = -log(softmax(logits[ti-1])[tid])        # 原始 NLL
nll_m = -log(softmax(logits_masked[ti-1])[tid]) # mask 掉 token c 后的 NLL
dnl = max(0.0, nll_m - nll_n)                   # ΔNLL ≥ 0
```

**数学正确性**:
- ΔNLL = NLL(masked) - NLL(original) ≥ 0 ✓
- mask 掉有因果影响的 token → NLL 增大 → ΔNLL > 0 ✓
- mask 掉无因果影响的 token → NLL 不变 → ΔNLL ≈ 0 ✓
- 这是标准 counterfactual probing 定义 ✓

**性能分析**:
- shenji-llama (469M): ~10 pps (pairs/sec)
- shehui-llama (27M): ~300 pps
- 变慢原因是模型规模，非算法错误

### 4.2 ccm_coverage_pct 语义审计

| 模式 | CCM_coverage 值 | 语义 | 正确性 |
|------|-----------------|------|--------|
| LIGHT | 0.0 | 不跑六战士 | ✓ |
| DEEP | 启发式覆盖率 | eligible/total | ⚠️ 非真实 CCM |
| SUPER | 0.0 | SUPER 不跑六战士 | ✓ |
| 旧任务 | 1.1e13 | id() 内存地址 | ✗ 已修复 |

---

## §5 缜密计划方法论

### 5.1 排查流程升级

```
旧流程 (有缺陷):
  代码审计 → API 测试 → (跳过前端验证) → 标记完成

新流程 (Round 24+):
  1. 前端界面审视 (用户看到什么?)
  2. 数据流追踪 (数据从哪来? 到哪去? 显示什么?)
  3. 三模式对比 (LIGHT vs DEEP vs SUPER, 字段完整性)
  4. 历史数据验证 (旧数据是否兼容? 列对齐? 值域?)
  5. API 契约测试 (HTTP 200 + 字段存在 + 值域)
  6. 代码审计 (算法正确性 + 性能)
  7. 浏览器端到端验证 (实际操作每个路径)
  8. 回归测试 (修复后不破坏已有功能)
```

### 5.2 检查清单 (每轮排查必过)

- [ ] 每个前端 UI 元素是否在三模式下都正确显示?
- [ ] 每个数值字段是否做了值域守卫?
- [ ] 历史数据是否兼容新代码? (列对齐? 类型一致?)
- [ ] 人话版报告是否包含所有分析结果?
- [ ] 进度条是否在每个阶段都有更新?
- [ ] 修复后服务是否重启? 运行时是否生效?
- [ ] CSS 缓存戳是否更新?

---

## §6 遗留问题

| 优先级 | 问题 | 建议 |
|--------|------|------|
| P3 | ADVANCED_PARAMETERS 未测试 | 下轮浏览器 E2E 验证 |
| P3 | SUPER 模式长文本 ΔNLL 波动验证 | 需手动跑 SUPER 任务 |
| P3 | 旧数据行重建 (从 result.json 重提取) | 如需历史数据可重建 |
| P3 | `_deploy_ccm` 实际调用 `ccm_with_convergence` | 启发式→真实 CCM |
