# Round 21 — export/md 科学描述性审查报告

> 创建: 2026-07-27
> 范围: trace-engine-web / trace-to-edm / edm-takens-web 三项目 export/md 端点
> 视角: 统计家 + PM
> 关联: ROUND21_ACTION_PLAN.md P0-C

---

## 0. 横向对比汇总

| 维度 | trace-engine-web | trace-to-edm | edm-takens-web |
|------|------------------|--------------|----------------|
| **章节数** | 9（7 主 + 2 附录） | 6 | 7 |
| **数值精度** | ATE 4位✓ / CI 3位 / obs 1位 — 不一致 | 仅 3 位 ✗ | ρ 3位 ✗ / p值 4位✓ / λ 4位✓ |
| **不确定性披露** | CI✓ / 样本量✓ / **缺 p 值** | **完全缺失** ✗ | p值✓ / Bonferroni✓ / **缺样本量+CCM ρ CI** |
| **局限说明** | SEM 标记✓ | **缺失** ✗ | HAVOK 退化✓ / **缺 SEM 标记** |
| **解读引导** | 5/7 主章节有✓ | 2/6 章节有 | 3/7 章节有 |
| **可视化替代** | ✓ 表头清晰 | ✓ 表头清晰 | ✓ 表头清晰 |
| **condition_number** | ✗ 数据有但不解读 (**P0**) | N/A | ✗ 算法有但不暴露 (**P0**) |
| **SEM 模拟标记** | ✓ | ✗ | ✗ |

---

## 1. P0 级问题（必须修复）

### P0-1: trace-engine-web condition_number 未在 export/md 解读

- **位置**: [routes/jobs.js](file:///f:/攻略/研发测试/TRACE%20Engine(EDM-Takens%20CCM)/trace-engine-web/routes/jobs.js#L380-L392)
- **问题**: `result.json` 第363行已写入 `condition_number: 113745413.6`（来源 `py_bridge.py:960`），但端点仅裸 dump `execution_profile`，无阈值比较或警告。
- **论文背景**: 已披露 condition_number=5.5×10¹² 病态问题，CI 不可信。
- **影响**: 用户看到 ATE/CI 但无法知晓其统计可信度。
- **修复**: 在概览节加 condition_number 诊断行，超 10¹⁰ 时显示警告。

### P0-2: edm-takens-web condition_number 未在 export/md 暴露

- **位置**: [routes/history.py](file:///f:/攻略/研发测试/Skill/edm-takens-web/backend/routes/history.py#L627-L645)
- **问题**: `sovereign_havok.py` 第624/677/692行已计算 `condition_number`，但 export/md 的 HAVOK 部分只显示 stability_tier/max_eigenvalue/rank/explained_variance/R²/kurtosis，未包含 condition_number。
- **影响**: HAVOK A 矩阵病态直接影响 stability_tier 可信度，但用户无法看到。
- **修复**: 在稳定性诊断节加 condition_number 行。

---

## 2. P1 级问题

### 2.1 数值精度不一致

| 端点 | 字段 | 当前精度 | 要求 | 行号 |
|------|------|---------|------|------|
| trace-engine-web | CI | 3 位 | 4 位 | jobs.js:278 |
| trace-engine-web | observed/counterfactual | 1 位 | 4 位 | jobs.js:342 |
| trace-to-edm | 所有数值 | 3 位 | 4 位 | server.js:603 |
| edm-takens-web | ρ | 3 位 | 4 位 | history.py:552 |

### 2.2 不确定性披露缺失

- **trace-to-edm**: 完全缺失 CI/p值/样本量不确定性
- **edm-takens-web**: 缺样本量（HAVOK 部分）、缺 CCM ρ 的 CI

### 2.3 SEM 模拟模式标记缺失

- **trace-to-edm**: 端点不暴露任何模式标记
- **edm-takens-web**: 全文件 grep `SEM|模拟` 在 export/md 函数体内无匹配

---

## 3. 各端点详细审查

### 3.1 trace-engine-web `GET /api/jobs/:id/export/md`

- **代码**: [routes/jobs.js:194-417](file:///f:/攻略/研发测试/TRACE%20Engine(EDM-Takens%20CCM)/trace-engine-web/routes/jobs.js#L194-L417)
- **9 节报告**: 概览/可识别性诊断/反驳测试/显著因果边/反事实扫描/概念词汇/配置附录/输入文本/原始report.md
- **优点**:
  - 第245-247行 modeNote 显式声明 SEM 模拟模式
  - 每节末尾有 `> **解读**:` 段落（5/7 主章节）
  - 表头设计清晰
- **缺点**:
  - condition_number 仅裸 dump 无解读 (P0-1)
  - 数值精度不一致 (P1)
  - top_edges 缺 p_value 列 (P2)

### 3.2 trace-to-edm `GET /api/trajectory/export/md`

- **代码**: [server.js:490-676](file:///f:/攻略/研发测试/TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/server.js#L490-L676)
- **6 节报告**: 概览/轨迹列解读/关键指标统计/轨迹数据预览/任务历史/一句话总结
- **优点**:
  - L1/L2/L3 schema 解读详尽
  - 表头清晰
- **缺点**:
  - 数值精度仅 3 位 (P1)
  - 无不确定性披露 (P1)
  - 趋势判定是简化启发式但未声明 (P1)
  - L3 列（z_福音等神圣投影）未披露是合成投影 (P2)

### 3.3 edm-takens-web `GET /api/history/{task_id}/export/md`

- **代码**: [routes/history.py:585-778](file:///f:/攻略/研发测试/Skill/edm-takens-web/backend/routes/history.py#L585-L778)
- **7 节报告**: 概览/稳定性诊断/EDM预测技能/CCM因果链/数据质量/配置附录/一句话总结
- **优点**:
  - Bonferroni 校正披露（第673行）
  - HAVOK 退化警告（第639行）
  - CCM 收敛判定显示（第684行）
- **缺点**:
  - condition_number 未暴露 (P0-2)
  - ρ 仅 3 位精度 (P1)
  - 缺样本量披露 (P1)
  - CCM 表缺 ρ 值及 CI (P1)
  - SEM 模拟标记缺失 (P1)

---

## 4. 4 角色互审

### PM 视角
- 用户看到 ATE=1.0183, CI=[0.9515, 1.0851] 无法知晓 condition_number=5.5×10¹² 下 CI 不可信 → P0 必须修
- trace-to-edm 完全无不确定性披露，用户可能误把简化启发式趋势当统计检验 → P1
- SEM 模拟模式标记在 2/3 端点缺失，用户可能误把合成 ATE 当真实 do-calculus → P1

### 统计家视角
- condition_number > 10¹⁰ 时 OLS 估计方差无穷大，CI 不可信，必须在报告中显式警告
- CCM 表缺 ρ 值是严重遗漏——p 值仅告知"是否显著"，ρ 才告知"效应多大"
- trace-to-edm 的趋势判定（前后半段均值比较）不是统计检验，应明确标注

### 算法工程师视角
- condition_number 已在算法层计算，端点层不暴露是"最后一公里"断裂
- 数值精度不一致是格式化函数设计缺陷，应用统一 `fmt(v, d=4)` 函数

### 数学家视角
- condition_number 与稳定性的数学关系：cond(A) > 1/ε_machine 时数值解不可信
- 对 HAVOK A 矩阵，cond(A) > 10¹⁰ 意味着特征值计算可能有 10 位有效数字丢失

---

## 5. 修复优先级

### 立即修复（Round 21 内）

| 优先级 | 问题 | 端点 | 修复复杂度 |
|--------|------|------|-----------|
| P0-1 | condition_number 解读 | trace-engine-web | 8 行 |
| P0-2 | condition_number 暴露 | edm-takens-web | 5 行 |
| P1 | ρ 精度 3→4 位 | edm-takens-web | 1 行 |
| P1 | CI 精度 3→4 位 | trace-engine-web | 2 行 |

### 待规划（Round 22+）

- trace-to-edm 不确定性披露全面补充
- SEM 模拟模式标记在 trace-to-edm 和 edm-takens-web 补齐
- CCM 表加 ρ 值及 CI 列
- 统一数值精度格式化函数

---

## 6. 验收清单

- [x] 3 WEB 项目 export/md 端点全部审查
- [x] 科学描述性 5 维评估完成
- [x] condition_number 诊断缺口识别 (2个P0)
- [x] SEM 模拟模式标记缺口识别
- [x] 4 角色互审完成
- [ ] P0-1/P0-2 立即修复（下一步）
- [ ] P1 数值精度统一（下一步）
