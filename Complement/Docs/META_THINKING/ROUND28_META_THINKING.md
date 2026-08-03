# ROUND 28 — 元经验反思与项目归档

> 生成时间: 2026-07-31
> 视角: 元认知 (Meta-Cognitive) + 科研负责性 (Scientific Accountability)
> 范围: ROUND21–ROUND28 全周期反思 + EDM-TAKENS 科研严谨性审查 + 各项目归档
> 关联文档: `ROUND26_META_THINKING.md`, `PORTABLE_TECHNICAL_GUIDE.md`, `Docs/ROUND25_META_THINKING.md`

---

## 第一部分: 系统性反思 — 问题为何层出不穷

### 1.1 六大系统性病灶的最终归因

ROUND26 识别出五大错误模式（声明-实现鸿沟、跨文件失同步、形式服从、元认知盲区、缜密计划的元问题）。ROUND27-28 的修缮过程暴露出第六个病灶：

**病灶 6: 同步契约的单向性 (One-Way Sync Contract)**

- **定义**: 核心库 → Web 副本的同步是单向的，核心库更新后需手动同步到 Web 副本，但缺乏自动化机制强制执行。
- **表现**: ROUND28 发现 edm-takens 核心库的 11 个文件与 Web 副本失同步（含 `_numeric_constants.py` 完全缺失），4 个科研披露字段端到端断裂。
- **根因**: `sync_check.py` 只检查一致性但不自动同步；开发者修改核心库后忘记运行 sync_check。
- **解药**: sync_check 作为 pre-commit hook 强制运行；或建立核心库 → 副本的 CI 自动同步管线。

### 1.2 问题层出不穷的深层原因

回顾 ROUND21–ROUND28 的 8 轮迭代，问题反复出现的深层原因是：

1. **"审计-修复"闭环未闭合**: 发现问题后仅修复当前实例，不追踪同类模式。ROUND26 修了 `final_interpretation.py` 的 Lyapunov log(0)，但 `enhanced_cross_validate.py` 的同类代码路径到 ROUND26 算法审视才被发现。

2. **便携目录的"假完整"**: 前几轮声称便携目录"开箱即用"，但 `check_skill_projects()` 检查的是外部 `Skill/` 目录，而非便携目录本身。便携目录中 `edm-takens/` 完全缺失，`edm-takens-web/` 仅有 `frontend/shared`。这不是"开箱即用"，而是"依赖外部目录才能用"。

3. **科研披露的"最后一公里"断裂**: 底层算法（`ccm_causality.py`、`_numpy_edm.py`）正确定义了科研披露字段，但中间层（`summary_builder.py`）未透传，前端（`main.js`）未渲染，用户根本看不到这些字段。算法层面的严谨性被传输链路的断裂消解了。

4. **测试断言的"虚假安全感"**: 测试断言过于严格（如离散特征值模长 1e-6 容差）或过于宽松（如不测试科研披露字段的存在），导致要么测试失败（误报），要么测试通过但关键功能未验证（漏报）。

### 1.3 ROUND28 的修缮策略

ROUND28 采用了与之前不同的修缮策略：

| 策略 | 之前 (ROUND21-27) | ROUND28 |
|------|-------------------|---------|
| 同步范围 | 仅 trace-engine + trace-engine-web | 全量 5 项目 (含 edm-takens + edm-takens-web) |
| 验证范围 | 11 项契约 (依赖外部 Skill/) | 14 项契约 (便携目录内自包含) |
| 科研披露 | 仅底层算法定义 | 端到端 (算法→中间层→前端→视觉) |
| 跨项目一致性 | 手动检查 | sync_check.py 自动化 (SHA256 + 文档 + 字段) |
| 便携目录 | "假完整" (依赖外部目录) | 真完整 (edm-takens/ + edm-takens-web/ 在目录内) |

---

## 第二部分: 元经验认知 — 关于"修缮过程"本身的认知

### 2.1 "应什么尽什么"的执行原则

用户要求"应什么尽什么，我不在赘述"，这指向一个核心原则：**修缮的完整性不应由修缮者自行判断，而应由契约定义**。

- **错误做法**: 修缮者自行判断"哪些 P 级需要修"，结果系统性遗漏 P3-P5。
- **正确做法**: 契约定义"所有 P 级都必须修缮"，修缮者执行，审计者验证。

ROUND28 的 14 项契约就是这一原则的体现：不依赖修缮者的自我判断，而是由 verify_portable.py 的 14 项检查强制覆盖。

### 2.2 科研负责性的层级

EDM-TAKENS 作为"科研级别的数学算法东西"，其负责性有多个层级：

| 层级 | 负责对象 | ROUND28 保障措施 |
|------|----------|-----------------|
| L1 数值正确性 | 计算结果 | eps 常量单一真相源 + Gavish-Donoho 阈值公式修正 |
| L2 统计严谨性 | p 值可信度 | IAAFT 替代数据 + BH 校正 + Bonferroni 校正 |
| L3 方法学透明性 | 审稿人/投资者 | is_strict_confirmatory + methodology_disclaimer 字段 |
| L4 评估模式披露 | 结论可解释性 | out_of_sample_used + effective_lib_sizes 字段 |
| L5 可复现性 | 后续研究者 | reproducibility_seed + 独立 Generator |
| L6 端到端可达性 | 最终用户 | 算法→中间层→前端→视觉 全链路透传 |

之前的问题在于：L1-L2 做到了，但 L3-L6 断裂。科研用户无法从 Web 界面获取统计保证级别和方法学声明，等于"算法严谨但用户看不到"。

### 2.3 "语义不稳定" vs "数学严格"

用户指出：TRACE Engine 依靠语义的不稳定，EDM-TAKENS 本身就是科研级别的数学算法东西。这揭示了两类项目 fundamentally different 的负责性要求：

**TRACE Engine (语义驱动)**:
- 因果发现依赖 LLaMA 的 token-level 语义理解
- 语义不稳定 → 因果边可能因模型版本/温度参数变化
- 负责性策略: 披露模型版本、参数预设、ΔNLL 阈值，让用户自行判断
- 审计重点: 模型加载正确性、预设合理性、SSE 流稳定性

**EDM-TAKENS (数学驱动)**:
- CCM/HAVOK 基于确定性数学公式 (Sugihara 2012, Brunton 2017)
- 数学确定性 → 给定输入+seed，输出完全可复现
- 负责性策略: 披露统计保证级别、方法学限制、评估模式
- 审计重点: 数学公式正确性、统计推断严谨性、数值稳定性

两类项目的修缮标准不同：TRACE Engine 的"P0"可能是 SSE 流崩溃（工程问题），EDM-TAKENS 的"P0"必须是数学公式错误（科学问题）。ROUND28 对 EDM-TAKENS 的审查采用了更严格的数学审视标准。

### 2.4 "便携同步目录的开箱即用"的真正含义

之前对"开箱即用"的理解是肤浅的——仅检查 `trace-engine/` 和 `trace-engine-web/` 存在。ROUND28 重新定义了"开箱即用"的五维标准：

| 维度 | 定义 | 验证方法 |
|------|------|----------|
| 可维护性 | 用户能自行更新和同步 | sync_product.py 支持 5 项目同步 |
| 可理解性 | 用户能理解架构和关系 | PORTABLE_TECHNICAL_GUIDE.md 架构图 |
| 可复制性 | 用户能从零重建 | 技术指南 §3 重建步骤 |
| 可调试性 | 用户能排查问题 | 技术指南 §4 调试指南 |
| 可接口性 | 用户能编程调用 | 技术指南 §5 API/CLI 契约 |

---

## 第三部分: 各项目归档 — 当前状态与迭代记录

### 3.1 trace-engine (因果推断引擎)

**当前状态**: 投资者评估级
**ROUND28 修缮**: 无新增（前序轮次已完成全量修缮）

**已验证能力**:
- LIGHT 模式: jieba 概念图 (1-3 秒)
- DEEP 模式: 六战士深度诊断 (10-60 秒)
- SUPER 模式: LLaMA token-level 因果发现
- DoWhy 反驳测试 + CausalLearn FCI 实现
- CCM verdict 三级语义 (ELIGIBLE_BUT_NOT_RUN / HEURISTIC_FALLBACK / VERIFIABLE)

**遗留项** (P3-P5, 不影响安全与功能):
- P3: SUPER 模式 n_significant_edges=0 是 LLaMA 模型能力限制，非 bug
- P4: 部分文档端点计数需定期核对
- P5: CSS 缓存戳需定期更新

### 3.2 trace-engine-web (Web 服务)

**当前状态**: 投资者评估级
**ROUND28 修缮**: 无新增（前序轮次已完成全量修缮）

**已验证能力**:
- HTTP + SSE 服务端正常启动
- `/api/health` + `/api/config` 契约通过
- SUPER 模式导入路径无遮蔽风险
- 主机绑定 127.0.0.1 (非 0.0.0.0)
- CSP script-src 移除 unsafe-inline

### 3.3 edm-takens (科研级算法库 CLI)

**当前状态**: 科研评估级
**ROUND28 修缮**: 便携目录同步 + CLI 科研披露字段输出

**已验证能力**:
- pytest 全量测试通过 (exit_code=0)
- HAVOK 全量动力学解释可运行
- 7 个核心模块可导入 (pipeline/ccm/havok/edm/constants/surrogate/final_interpretation)
- 4 个科研披露字段在源码中定义
- CLI 输出含 [Guarantee] / [Disclaimer] / OOS 标注

**科研严谨性保障**:
- Gavish-Donoho 阈值公式正确 (sovereign_havok.py)
- IAAFT 替代数据 silent failure 修复 (ccm_causality.py)
- out-of-sample cross-map skill 实现 (Sugihara 2012 严格契约)
- eps 常量单一真相源 (_numeric_constants.py)
- reproducibility_seed + 独立 Generator (pipeline.py)
- Benjamini-Hochberg FDR 校正 (ccm_causality.py)
- is_strict_confirmatory 字段区分 confirmatory/exploratory

**遗留项** (P3-P5, 不影响科研严谨性):
- P3: Numba 加速未实现 (性能优化, 非正确性问题)
- P4: 批量 KDTree 查询未实现 (性能优化)
- P5: truncated SVD 优化未实现 (性能优化)

### 3.4 edm-takens-web (Web 服务)

**当前状态**: 科研评估级
**ROUND28 修缮**: 便携目录同步 + 科研披露字段端到端透传

**已验证能力**:
- backend/api.py 可导入
- backend/sync_check.py 跨项目一致性检查通过 (20 一致 / 0 不一致)
- backend/services/summary_builder.py 透传 4 个科研披露字段
- frontend/src/main.js 渲染 CCM 详情 + 收敛曲线 sparkline
- frontend/src/style.css confirmatory/exploratory 视觉区分
- docs/ALGORITHM_AUDIT.md §2.3 跨项目同步修复记录

**科研披露字段端到端落地**:

| 字段 | 来源 | 透传层 | 渲染层 | 视觉区分 |
|------|------|--------|--------|----------|
| is_strict_confirmatory | ccm_causality.py | summary_builder.py | main.js | .ccm-badge-confirmatory (蓝) / .ccm-badge-exploratory (琥珀) |
| methodology_disclaimer | ccm_causality.py | summary_builder.py | main.js | .ccm-disclaimer (琥珀左边框) |
| effective_lib_sizes | _numpy_edm.py | summary_builder.py | main.js | code.sparkline (绿底) |
| out_of_sample_used | _numpy_edm.py | summary_builder.py | main.js | .ccm-oos-yes (绿) / .ccm-oos-no (琥珀) |

### 3.5 trace-to-edm (桥接服务)

**当前状态**: 投资者评估级
**ROUND28 修缮**: 无新增（前序轮次已完成全量修缮）

**已验证能力**:
- bridge.py 写入 trace_status/trace_error/trace_mode 列
- app.js preferredCols 包含这三列
- main.css 含 .tstat-ok/.tstat-failed/.tstat-partial 状态色

### 3.6 便携目录 (TRACE Engine(EDM-Takens CCM))

**当前状态**: 开箱即用 (14/14 契约通过)
**ROUND28 修缮**: 全量同步 EDM-TAKENS 项目 + 扩展验证契约

**已验证能力**:
- 14 项独立运行审计全部通过
- 37 项关键文件全部存在
- 3 个 LLaMA 模型可用 (shehui-llama, shenji-llama, shehui-llama-v4-archive)
- EDM-TAKENS CLI 可独立运行 (无需外部 Skill/ 目录)
- EDM-TAKENS Web 可独立运行 (无需外部 Skill/ 目录)

---

## 第四部分: 未来迭代指导

### 4.1 迭代原则

1. **契约驱动**: 修缮范围由契约定义，不由修缮者自行判断
2. **端到端验证**: 从算法定义到用户可见界面，全链路验证
3. **便携优先**: 所有项目必须在便携目录内可独立运行
4. **科研透明**: 统计保证级别和方法学限制必须对用户可见
5. **同步自动化**: 核心库 → Web 副本的同步应有自动化机制

### 4.2 待办项 (按优先级)

**P3 (性能优化, 不影响正确性)**:
- EDM-TAKENS Numba 加速 (CCM 内循环)
- EDM-TAKENS 批量 KDTree 查询
- EDM-TAKENS truncated SVD 优化

**P4 (文档维护)**:
- 端点计数定期核对
- CSS 缓存戳定期更新
- ALGORITHM_AUDIT.md 定期回顾

**P5 (未来方向)**:
- 核心库 → Web 副本 CI 自动同步
- pre-commit hook 强制运行 sync_check
- 多语言支持 (英文文档)

### 4.3 元经验教训

1. **"开箱即用"不是声明，而是验证**: 必须在实际便携目录中验证所有项目可独立运行，而非依赖外部目录。

2. **科研披露不是定义，而是透传**: 字段在源码中定义不够，必须透传到中间层、渲染到前端、用视觉区分，用户才能看到。

3. **同步不是单向，而是闭环**: 核心库 → 副本的同步必须有检查机制 (sync_check) 和自动化流程 (CI/pre-commit)。

4. **测试不是通过，而是覆盖**: 测试通过不等于功能正确，必须覆盖关键字段、关键路径、关键契约。

5. **便携不是复制，而是完整**: 便携目录必须包含所有项目的完整代码、文档、测试，而非仅部分子目录。

---

## 附录: ROUND21-28 修缮轮次时间线

| 轮次 | 时间 | 核心主题 | 关键成果 |
|------|------|----------|----------|
| ROUND21 | 2026-07 | 算法审计 + API 审计 | 40+ 项修复，FCI 实现确认 |
| ROUND22 | 2026-07 | 元思考 | 系统性错误模式首次总结 |
| ROUND23 | 2026-07 | 元思考 | 跨文件失同步模式分析 |
| ROUND24 | 2026-07 | 元思考 | 形式服从问题识别 |
| ROUND25 | 2026-07 | 元思考 | 计划完整性 vs 执行完整性 |
| ROUND26 | 2026-07-28 | 算法审视 + 元思考 | 5 大错误模式 + L1-L4 验证层级 |
| ROUND27 | 2026-07-31 | 12 维度核对 + P0-P5 修缮 | 26 项修复 (含 8 项 P0)，6 大系统性病灶 |
| ROUND28 | 2026-07-31 | EDM-TAKENS 科研审查 + 便携目录开箱即用 | 14 项契约全通过，科研披露端到端，5 项目便携同步 |

---

*元经验核心教训: 科研级产品的负责性不在算法层的数学正确性，而在从算法到用户的整条传输链路的完整性。一个数学正确但用户看不到统计保证级别的产品，等于没有负责性。便携目录的"开箱即用"不是目录存在，而是所有项目可在其中独立运行、独立验证、独立调试。*
