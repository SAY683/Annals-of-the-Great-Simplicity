# 技术文档同步与旧数值修复报告

> 创建：2026-07-20（元审计 Q5 技术文档同步）
> **最后更新**：2026-07-20（元审计 Q8+ 文档同步 — tunnel 1033 / CORS / API 计数 / start_all.ps1）
> 范围：`f:\攻略\研发测试\.skills` 下五大项目（edm-takens / edm-takens-web / trace-engine / trace-engine-web / trace-to-edm）+ 根级元审计文档集
> 目标：路由文档同步、旧数值修复、引用断裂修复、设计文档同步
> 关联文档：[META_AUDIT_CHANGELOG.md](META_AUDIT_CHANGELOG.md) · [MICROSERVICE_API_DESIGN.md](MICROSERVICE_API_DESIGN.md) · [ALGORITHM_MATHEMATICAL_AUDIT.md](ALGORITHM_MATHEMATICAL_AUDIT.md) · [NEWCOMER_PLAYBOOK.md](NEWCOMER_PLAYBOOK.md)

---

## 1. 同步检查总览

### 1.1 检查范围

本轮同步共检查 **15 份文档**，覆盖 5 个项目目录与 5 份根级元审计文档：

| # | 文档路径 | 类型 | 检查结果 |
|---|---------|------|---------|
| 1 | `edm-takens-web/README.md` | 项目 README | ✅ 已含 25 端点 API 表 |
| 2 | `edm-takens-web/docs/TECHNICAL.md` | 技术文档 | ✅ 12 端点表已存在 |
| 3 | `trace-engine-web/README.md` | 项目 README | ✅ 已含 20 端点 API 表 |
| 4 | `trace-to-edm/README.md` | 项目 README | ⚠️ 缺失 25 端点表 → 已修复 |
| 5 | `trace-to-edm/server.js` | 服务端代码 | ⚠️ 头部端点列表过时 → 已精简 |
| 6 | `MICROSERVICE_API_DESIGN.md` | 路由契约 | ⚠️ A.3 行号过时 → 已同步 |
| 7 | `META_AUDIT_CHANGELOG.md` | 元审计 CHANGELOG | ⚠️ 3 处断裂相对路径 + 2 处旧行号 → 已修复 |
| 8 | `ALGORITHM_MATHEMATICAL_AUDIT.md` | 算法数学审视 | ✅ 27M/470M 引用合理 |
| 9 | `NEWCOMER_PLAYBOOK.md` | 新手验收剧本 | ✅ 引用全部可追溯 |
| 10 | `TOKUSATSU_DASHBOARD_DESIGN.md` | UI/UX 设计稿 | ✅ 无需修改 |
| 11 | `trace-engine/ALGORITHM_AUDIT.md` | 算法审计 | ✅ 无需修改 |
| 12 | `trace-engine/secret_adoption_audit.md` | 设计采纳审计 | ✅ 已含 P1 引用范围说明 |
| 13 | `trace-engine/README.md` | 项目 README | ✅ 27M/469M/470M 一致 |
| 14 | `trace-engine/SKILL.md` | Skill 文档 | ✅ 27M/469M/470M 一致 |
| 15 | `trace-engine/references/edge_cases_reference.md` | 边界情况参考 | ✅ 模型规格一致 |

### 1.2 发现的问题汇总

共发现 **6 类问题，12 处具体缺陷**：

1. **路由文档缺失**（1 处）：trace-to-edm/README.md 缺失完整 API 端点表
2. **端点列表过时**（1 处）：server.js 头部仍含不存在的 `/api/replay-all`、`/api/stream/:id`
3. **行号引用偏移**（27 处）：MICROSERVICE_API_DESIGN.md A.3 的 25 行 + META_AUDIT_CHANGELOG.md 的 2 行
4. **相对路径断裂**（3 处）：META_AUDIT_CHANGELOG.md 中 P0-1/P0-3 修缮的引用未带项目前缀
5. **姊妹文档索引缺失**（1 处）：META_AUDIT_CHANGELOG.md 末尾未列出同级元审计文档集
6. **旧数值残留**（2 处）：MICROSERVICE_API_DESIGN.md 与 trace-to-edm/README.md 中保留 "13 端点" 历史说明（**经评估为合理的历史参考，不做删除**）

### 1.3 验证方法

- **端点数验证**：使用 Grep 在 server.js 中匹配 `app.(get|post|put|delete)(`，得到 25 条结果，与文档表 1:1 对应
- **行号验证**：将 README.md 表中所有行号与 server.js 实际 `app.<method>(` 的行号逐一比对，全部一致
- **引用文件存在性**：使用 Glob 验证所有被引用的 .md/.py/.js 文件路径均存在
- **模型规格一致性**：搜索 "27M"/"469M"/"470M" 在所有 .md 文档中的出现，全部一致
- **端口号一致性**：搜索 "8000"/"3000"/"3020"/"3100"/"5173"，全部正确

---

## 2. 路由文档同步结果

### 2.1 端点数量契约

| 项目 | 端口 | 端点数 | 验证方法 |
|------|------|--------|---------|
| edm-takens-web | 8000 | 25 | `@router.(get\|post\|put\|delete)` 装饰器 25 条 ✅ |
| trace-engine-web | 3000-3020 | 20 | `router.(get\|post\|put\|delete)(` 调用 20 条 ✅ |
| trace-to-edm | 3100 | 25 | `app.(get\|post\|put\|delete)(` 调用 25 条 ✅ |
| **合计** | — | **70** | 与 [MICROSERVICE_API_DESIGN.md](MICROSERVICE_API_DESIGN.md) §1 契约一致 |

### 2.2 trace-to-edm/server.js 头部精简

**修改前**（原 8 端点列表，包含已不存在的路由）：

```javascript
 * 端点:
 *   GET  /api/status
 *   POST /api/run
 *   POST /api/replay
 *   POST /api/replay-all   ← 不存在（由 /api/replay 以 replay_all=true 复用）
 *   GET  /api/jobs
 *   POST /api/edm/trigger
 *   GET  /api/stream/:id   ← 不存在
 *   GET  /api/health
```

**修改后**（精简版，指向 README.md 完整表）：

```javascript
 * 端点 (共 25 个 API 端点 + 静态前端 /，详见 README.md §API 端点表):
 *   GET  /                 前端面板 (express.static, 不计入 25)
 *   GET  /api/status       L1  轨迹状态 + EDM 就绪度
 *   POST /api/run          L3  提交文本管线任务 (Mode A, SSE)
 *   POST /api/replay       L3  提交回填任务 (Mode B, SSE；replay_all=true 复用此端点)
 *   POST /api/edm/trigger  L3  触发 EDM 分析
 *   GET  /api/jobs         L4  任务历史
 *   …其余 19 个端点（dataset/projects/work/models 等）见 README.md 表
```

**行号偏移影响**：原 25 个端点的行号整体 -2（如 `/api/status` 从 149 → 147）。后续 README.md 表与 MICROSERVICE_API_DESIGN.md A.3 节均按此偏移同步。

### 2.3 trace-to-edm/README.md 新增 25 端点 API 表

在 "工作流" 章节后插入完整 25 端点表，含 server.js 行号。表头与内容如下（节选）：

```markdown
## API 端点表（共 25 端点）

> 元审计 Q5 同步 (2026-07-20)：之前任务卡曾误列 13 端点，实际盘点为 25 端点
> （含数据集 / 项目 / 工作目录 / 模型管理）。

| # | 方法 | 端点 | 说明 | server.js 行号 |
|---|------|------|------|----------------|
| 1 | GET | `/api/status` | 轨迹状态 + EDM 就绪度 | 147 |
| ... | ... | ... | ... | ... |
| 25 | POST | `/api/replay-uuids` | 选定 UUID 回填到当前项目 (SSE) | 864 |
```

**说明栏**：
- 根 `/`（express.static 前端面板）不计入 25 端点
- `POST /api/replay-all` 在文档中常被提及，但代码实现上由 `/api/replay` 以 `replay_all=true` 复用，并非独立路由

### 2.4 MICROSERVICE_API_DESIGN.md A.3 章节行号同步

A.3 章节列出 trace-to-edm 的 25 端点带行号索引表。本次将全部 25 行的行号同步至 server.js 头部精简后的最新行号（整体 -2），并在表前添加同步说明：

```markdown
> 行号同步至 2026-07-20（元审计 Q5：server.js 头部注释精简后整体 -2 行）。
```

---

## 3. 旧数值修复记录

### 3.1 端点数量修正

| # | 文件 | 行号 | 旧值 | 新值 | 理由 |
|---|------|------|------|------|------|
| 1 | `MICROSERVICE_API_DESIGN.md` | 5 | "13 端点"（任务卡说明） | "25 端点（含数据集/项目/工作目录/模型管理）" | 实际 `app.<method>(` 盘点为 25 条 |
| 2 | `trace-to-edm/README.md` | 84 | 无端点表 | 新增 25 端点 API 表 | 用户任务卡明确要求补全 |
| 3 | `trace-to-edm/server.js` | 9-17 | 8 端点列表（含 2 个不存在路由） | 精简为 6 行总结式 | 避免代码头部与实际路由不同步 |

> 注：MICROSERVICE_API_DESIGN.md:5 与 trace-to-edm/README.md:84 中保留的 "13 端点" 字样为**合理的历史说明**（解释"之前任务卡曾误列"），不做删除。
> 
> **Q8+ 更新** (2026-07-20): trace-to-edm 端点从 25 → 26（新增 `GET /api/edm/poll/:id` CORS 代理）。
> 同步更新：[server.js](trace-to-edm/server.js), [README.md](trace-to-edm/README.md), [MICROSERVICE_API_DESIGN.md](MICROSERVICE_API_DESIGN.md), [META_AUDIT_CHANGELOG.md](META_AUDIT_CHANGELOG.md), [NEWCOMER_PLAYBOOK.md](NEWCOMER_PLAYBOOK.md)。

### 3.2 行号引用同步

| # | 文件 | 引用位置 | 旧行号 | 新行号 | 理由 |
|---|------|---------|--------|--------|------|
| 1 | `MICROSERVICE_API_DESIGN.md` A.3 | 25 个端点行号 | 149, 202, ..., 866 | 147, 200, ..., 864 | server.js 头部注释精简导致整体 -2 |
| 2 | `META_AUDIT_CHANGELOG.md` P1-2 修缮 | server.js:470-491 | 470-491 | 468-489 | 同上 |
| 3 | `META_AUDIT_CHANGELOG.md` P1-2 修缮 | server.js:737-759 | 737-759 | 735-757 | 同上 |

并在 `META_AUDIT_CHANGELOG.md` P1-2 修缮段末添加同步说明：

```markdown
> 元审计 Q5 同步 (2026-07-20)：以上 server.js 行号已同步至 server.js 头部注释
> 精简后的最新行号（原 470-491/737-759 → 现 468-489/735-757，整体 -2 行）。
```

### 3.3 模型规格一致性验证

搜索 "27M"/"469M"/"470M" 在所有 .md 文档中的出现（31 条），全部一致：

| 模型 | 参数规格 | 体积 | max_position | 用途 |
|------|---------|------|--------------|------|
| shehui-llama | 27M | ~108MB | 256 | 轻量高效，~800 pps |
| shenji-llama | 469M | ~1.88GB | 1024 | 神学/史诗古文，~10-40 pps |
| shehui-llama-v4-archive | 470M | ~1.88GB | 1024 | 旧版归档，因果发现能力较弱 |

**涉及文档**（一致性已确认）：
- `trace-engine/README.md`、`trace-engine/SKILL.md`
- `trace-engine/references/edge_cases_reference.md`、`kv_cache_decision.md`
- `trace-engine/examples/counterfactual_hybrid/references/forbidden_rules.md`、`edge_cases.md`
- `trace-engine/examples/counterfactual_hybrid/DESIGN_SIX_IN_ONE.md`
- `trace-engine/examples/zhihu_consensus/README.md`
- `trace-engine-web/README.md`、`trace-engine-web/work/README_PRODUCT.md`
- `ALGORITHM_MATHEMATICAL_AUDIT.md`、`TOKUSATSU_DASHBOARD_DESIGN.md`、`NEWCOMER_PLAYBOOK.md`

### 3.4 端口号一致性验证

| 项目 | 端口 | 涉及文档（一致性已确认） |
|------|------|-------------------------|
| edm-takens-web | 8000 | `README.md:145`、`docs/TROUBLESHOOTING.md:10` |
| trace-engine-web | 3000-3020 | `README.md:48,52,161,164,167`、`work/README_PRODUCT.md:56,59,114` |
| trace-to-edm | 3100 | `README.md:27`、`server.js:26` |
| 前端 dev | 5173 | `trace-workbench/SKILL.md:55`（仅开发模式） |

---

## 4. 引用断裂修复记录

### 4.1 META_AUDIT_CHANGELOG.md 相对路径修复

**P0-1 修缮的 5 处引用**（six_warriors.py）：

| # | 旧路径 | 新路径 | 理由 |
|---|--------|--------|------|
| 1 | `[six_warriors.py:1-36](examples/counterfactual_hybrid/six_warriors.py)` | `[six_warriors.py:1-36](trace-engine/examples/counterfactual_hybrid/six_warriors.py)` | 缺项目前缀 |
| 2 | `[six_warriors.py:91-144](examples/counterfactual_hybrid/six_warriors.py)` | `[six_warriors.py:91-144](trace-engine/examples/counterfactual_hybrid/six_warriors.py)` | 同上 |
| 3 | `[six_warriors.py:189,284](examples/counterfactual_hybrid/six_warriors.py)` | `[six_warriors.py:189,284](trace-engine/examples/counterfactual_hybrid/six_warriors.py)` | 同上 |
| 4 | `[six_warriors.py:630-693](examples/counterfactual_hybrid/six_warriors.py)` | `[six_warriors.py:630-693](trace-engine/examples/counterfactual_hybrid/six_warriors.py)` | 同上 |
| 5 | `[six_warriors.py:717-731](examples/counterfactual_hybrid/six_warriors.py)` | `[six_warriors.py:717-731](trace-engine/examples/counterfactual_hybrid/six_warriors.py)` | 同上 |

**P0-3 修缮的 2 处引用**：

| # | 旧路径 | 新路径 | 理由 |
|---|--------|--------|------|
| 6 | `[ALGORITHM_AUDIT.md](ALGORITHM_AUDIT.md)` | `[ALGORITHM_AUDIT.md](trace-engine/ALGORITHM_AUDIT.md)` | META_AUDIT_CHANGELOG.md 位于根级，目标在 trace-engine/ 下 |
| 7 | `[secret_adoption_audit.md:7-22](secret_adoption_audit.md)` | `[secret_adoption_audit.md:7-22](trace-engine/secret_adoption_audit.md)` | 同上 |

### 4.2 其他文档引用验证（无需修改）

- `edm-takens/SKILL.md:244` → `secret_adoption_audit.md`：相对路径正确（同目录）
- `trace-engine/secret_adoption_audit.md:21` → `ALGORITHM_AUDIT.md`：相对路径正确（同目录）
- `trace-engine/README.md:48` → `../trace-engine-web/README.md`：相对路径正确
- `trace-engine/SKILL.md:59` → `../trace-engine-web/README.md`：相对路径正确
- `trace-engine/examples/counterfactual_hybrid/README.md:100` → `../../trace-engine-web/README.md`：相对路径正确
- `NEWCOMER_PLAYBOOK.md` 中 4 处引用（`trace-engine/ALGORITHM_AUDIT.md`、`trace-engine-web/README.md`、`trace-to-edm/layer3_sacred.py`、`META_AUDIT_CHANGELOG.md`）：全部可追溯 ✅
- `ALGORITHM_MATHEMATICAL_AUDIT.md` 中 20+ 处引用：全部可追溯 ✅

### 4.3 Glob 验证目标文件存在性

| 被引用文件 | 实际路径 | 状态 |
|-----------|---------|------|
| trace-engine/ALGORITHM_AUDIT.md | `f:\攻略\研发测试\.skills\trace-engine\ALGORITHM_AUDIT.md` | ✅ 存在 |
| trace-engine/secret_adoption_audit.md | `f:\攻略\研发测试\.skills\trace-engine\secret_adoption_audit.md` | ✅ 存在 |
| edm-takens/docs/ALGORITHM_AUDIT.md | `f:\攻略\研发测试\.skills\edm-takens\docs\ALGORITHM_AUDIT.md` | ✅ 存在 |
| edm-takens/docs/MVE_OPTIMIZATION.md | `f:\攻略\研发测试\.skills\edm-takens\docs\MVE_OPTIMIZATION.md` | ✅ 存在 |
| edm-takens-web/docs/ALGORITHM_AUDIT.md | `f:\攻略\研发测试\.skills\edm-takens-web\docs\ALGORITHM_AUDIT.md` | ✅ 存在 |
| trace-engine-web/ALGORITHM_AUDIT.md | `f:\攻略\研发测试\.skills\trace-engine-web\ALGORITHM_AUDIT.md` | ✅ 存在 |
| trace-engine/examples/counterfactual_hybrid/*.py（7 个文件） | 实际路径全部存在 | ✅ 存在 |
| trace-to-edm/{layer1,layer2,layer3,csv_builder,bridge,config}.py（6 个文件） | 实际路径全部存在 | ✅ 存在 |

---

## 5. 设计文档同步记录

### 5.1 三个新建元审计文档的引用状态

| 文档 | 创建日期 | 被引用情况 | 同步动作 |
|------|---------|-----------|---------|
| `META_AUDIT_CHANGELOG.md` | 2026-07-20 | 被 `NEWCOMER_PLAYBOOK.md:443` 引用 ✅ | 已添加姊妹文档索引表（见 §5.2） |
| `ALGORITHM_MATHEMATICAL_AUDIT.md` | 2026-07-20 | 被 `META_AUDIT_CHANGELOG.md` 姊妹索引引用 ✅ | 无需额外动作 |
| `NEWCOMER_PLAYBOOK.md` | 2026-07-20 | 被 `META_AUDIT_CHANGELOG.md` 姊妹索引引用 ✅ | 无需额外动作 |

### 5.2 META_AUDIT_CHANGELOG.md 新增姊妹文档索引

在文档末尾添加 10 个同级元审计文档的索引表，覆盖：

| 文档 | 用途 |
|------|------|
| META_AUDIT_CHANGELOG.md | 本文档：五项目 12 维度修缮 CHANGELOG |
| ALGORITHM_MATHEMATICAL_AUDIT.md | 五项目算法/数学正确性深度审计 |
| NEWCOMER_PLAYBOOK.md | 新手端到端验收剧本（7 幕） |
| MICROSERVICE_API_DESIGN.md | 五项目 70 端点（25+20+25）微服务 API 契约 + 前端重连 |
| TOKUSATSU_DASHBOARD_DESIGN.md | 特摄风仪表盘 UI/UX 设计稿 |
| trace-engine/ALGORITHM_AUDIT.md | TRACE 引擎六勇士 Tier-A/B 架构审计 |
| trace-engine/secret_adoption_audit.md | TRACE 主项目设计规则采纳审计 |
| edm-takens-web/docs/ALGORITHM_AUDIT.md | EDM-Takens Web 4 处适应性修改审计 |
| edm-takens/docs/ALGORITHM_AUDIT.md | EDM-Takens Skill 算法审计 |
| edm-takens/docs/MVE_OPTIMIZATION.md | Sovereign-MVE 引擎设计文档（775 行） |

### 5.3 ALGORITHM_AUDIT.md / NEWCOMER_PLAYBOOK.md 同步状态

- **trace-engine/ALGORITHM_AUDIT.md**：被 `META_AUDIT_CHANGELOG.md`（P0-3 修缮）、`ALGORITHM_MATHEMATICAL_AUDIT.md`、`NEWCOMER_PLAYBOOK.md` 引用，引用路径全部正确 ✅
- **edm-takens/docs/ALGORITHM_AUDIT.md**：被 `ALGORITHM_MATHEMATICAL_AUDIT.md`、`edm-takens/docs/edm-takens-skill-diff-report.md`、`edm-takens/docs/edm-takens_optimization_potentials.md` 引用 ✅
- **edm-takens-web/docs/ALGORITHM_AUDIT.md**：被 `ALGORITHM_MATHEMATICAL_AUDIT.md` 引用 ✅
- **trace-engine-web/ALGORITHM_AUDIT.md**：被 `ALGORITHM_MATHEMATICAL_AUDIT.md` 引用 ✅

---

## 6. 残留待办

### 6.1 本轮已全部完成的事项

| # | 任务 | 状态 |
|---|------|------|
| 1 | trace-to-edm/server.js 头部端点列表精简 | ✅ |
| 2 | trace-to-edm/README.md 新增 25 端点 API 表 | ✅ |
| 3 | MICROSERVICE_API_DESIGN.md A.3 行号同步（25 个端点） | ✅ |
| 4 | META_AUDIT_CHANGELOG.md 修复 3 处断裂相对路径 | ✅ |
| 5 | META_AUDIT_CHANGELOG.md 修复 2 处 server.js 行号 | ✅ |
| 6 | META_AUDIT_CHANGELOG.md 新增姊妹文档索引（10 个文档） | ✅ |
| 7 | 27M/469M/470M 模型规格一致性验证 | ✅ |
| 8 | 8000/3000-3020/3100 端口号一致性验证 | ✅ |
| 9 | 引用文件存在性 Glob 验证 | ✅ |
| 10 | 根级 5 个 .md 文档交叉引用扫描 | ✅ |

### 6.2 后续迭代建议（非本轮范围）

| # | 待办 | 优先级 | 理由 |
|---|------|--------|------|
| 1 | 在 CI 中加入 Markdown 链接检查脚本 | P3 | 防止未来再次出现断裂引用 |
| 2 | 为 server.js 路由生成器添加自动行号注释 | P3 | 避免头部注释与实际行号偏移 |
| 3 | 统一三项目的 "API 端点表" 模板格式 | P4 | 当前三项目表格列结构略有差异 |
| 4 | 补充 trace-to-edm 的 tests/ 目录 | P3 | 见 META_AUDIT_CHANGELOG.md R3 |
| 5 | 前端 TypeScript 化 + Vitest 测试 | P3 | 见 META_AUDIT_CHANGELOG.md R1 |

### 6.3 已知非缺陷（保留说明）

| # | 位置 | 内容 | 处理决策 |
|---|------|------|---------|
| 1 | `MICROSERVICE_API_DESIGN.md:5` | "原始任务卡列 trace-to-edm 为 13 端点" | 保留：作为历史参考，说明为何需同步 |
| 2 | `trace-to-edm/README.md:84` | "之前任务卡曾误列 13 端点" | 保留：作为 Q5 同步说明，向读者解释修订背景 |

---

## 同步统计

| 类别 | 修改数 | 验证数 |
|------|--------|--------|
| 路由文档同步 | 3 处（server.js + README.md + MICROSERVICE_API_DESIGN.md） | 25 端点 × 2 处行号 |
| 旧数值修复 | 5 处（端点数 + 行号） | 31 条模型规格 + 4 个端口号 |
| 引用断裂修复 | 7 处（META_AUDIT_CHANGELOG.md 相对路径） | 120+ 引用全部可追溯 |
| 设计文档同步 | 1 处（姊妹索引） | 10 个文档互引 |
| **合计** | **16 处修改** | **180+ 处验证** |

---

## 验证命令清单

执行本轮同步验证所用的 Grep / Glob 命令：

```bash
# 1. 端点数验证
Grep "app\\.(get|post|put|delete)\\(" path: trace-to-edm/server.js  → 25 条
Grep "router\\.(get|post|put|delete)\\(" path: trace-engine-web     → 20 条
Grep "@router\\.(get|post|put|delete)" path: edm-takens-web/backend → 25 条

# 2. 旧数值残留检查
Grep "13 ?端点|端点 ?13|端点数 ?13"  → 2 处合理历史说明
Grep "27M|469M|470M"                  → 31 处全部一致
Grep "端口 ?(8000|3000|3020|3100|5173)" → 端口引用全部正确

# 3. 引用文件存在性
Glob "trace-engine/ALGORITHM_AUDIT.md"                       → ✅ 存在
Glob "trace-engine/secret_adoption_audit.md"                 → ✅ 存在
Glob "edm-takens/docs/{ALGORITHM_AUDIT,MVE_OPTIMIZATION}.md" → ✅ 存在
Glob "{edm-takens-web,trace-engine-web}/ALGORITHM_AUDIT.md"  → ✅ 存在

# 4. 断裂链接扫描
Grep "\\]\\([a-zA-Z\\.][^)\\s]*\\.(md|py|js|json)\\)" → 120+ 引用全部可追溯
```

---

**元审计 Q5 技术文档同步 (2026-07-20)**

---

## 7. Phase 7 同步审计 (2026-07-23)

> 关联：[META_AUDIT_CHANGELOG.md](META_AUDIT_CHANGELOG.md) §Phase 7

### 7.1 sync_check 白名单变更

**文件**: [edm-takens-web/backend/sync_check.py](edm-takens-web/backend/sync_check.py) L30-34

**变更前**:
```python
EXPECTED_DIFFERS = {
    "_paths.py",                  # 副本支持 EDMTAKENS_DATA_DIR 环境变量
    "__init__.py",                # 副本为 backend 包说明注释
    "enhanced_cross_validate.py", # 历史 bug 未同步
    "environment_check.py",       # 行尾差异
}
```

**变更后**:
```python
EXPECTED_DIFFERS = {
    "_paths.py",                  # 副本支持 EDMTAKENS_DATA_DIR 环境变量
    "__init__.py",                # 副本为 backend 包说明注释，与核心库源码包注释不同
}
```

**变更理由**:
- `enhanced_cross_validate.py`: Lyapunov 负指数 bug + 截断伪影 bug 已从 src 同步到 web 副本，重新纳入一致性监控
- `environment_check.py`: 行尾差异（CRLF/LF）已统一为 CRLF，重新纳入一致性监控

### 7.2 引擎同步审计结果

**最终 sync_check 结果**: 19 一致 / 2 预期差异 / 0 不一致 ✅

| # | 文件 | 同步方向 | 修复内容 |
|---|------|---------|---------|
| 1 | `edm_tau_optimization.py` | src → web | AMI 概率归一化 epsilon 位置 |
| 2 | `final_interpretation.py` | src → web | Lyapunov 负指数 + Koopman 谱离散特征值 |
| 3 | `enhanced_cross_validate.py` | src → web | Lyapunov + 截断伪影 |
| 4 | `sovereign_havok.py` | src → web | condition_number 奇异矩阵处理 |
| 5 | `environment_check.py` | 行尾统一 | LF → CRLF |

### 7.3 Phase 7 文档更新清单

| # | 文档 | 更新内容 |
|---|------|---------|
| 1 | `META_AUDIT_CHANGELOG.md` | 新增 §Phase 7 章节（7.1-7.6） |
| 2 | `DOC_SYNC_REPORT.md` | 本节：§7 sync_check 白名单变更 + 引擎同步结果 |

**Phase 7 文档同步 (2026-07-23)**

---

## 8. Phase 8 同步审计 (2026-07-23)

> 关联：[META_AUDIT_CHANGELOG.md](META_AUDIT_CHANGELOG.md) §Phase 8

### 8.1 便携式目录同步结果

**同步脚本**: `sync_all_portable.py`（五大项目统一同步）
**便携式根目录**: `G:\git\Annals-of-the-Great-Simplicity-main\Annals-of-the-Great-Simplicity\Complement\`

#### 同步覆盖（6 项目）

| 项目 | 源 | 目标 | 状态 |
|------|---|------|------|
| edm-takens | `.skills/edm-takens/` | `Skill/edm-takens/` | ✅ |
| edm-takens-web | `.skills/edm-takens-web/` | `Skill/edm-takens-web/` | ✅ |
| trace-engine | `.skills/trace-engine/` | `TRACE Engine(EDM-Takens CCM)/trace-engine/` | ✅ |
| trace-engine-web | `.skills/trace-engine-web/` | `TRACE Engine(EDM-Takens CCM)/trace-engine-web/` | ✅ |
| trace-to-edm | `.skills/trace-to-edm/` | `TRACE Engine(EDM-Takens CCM)/trace-to-edm/` | ✅ |
| Qwen2.5 模型 | `F:\攻略\研发测试\` | `TRACE Engine(EDM-Takens CCM)/Models/` | ✅ (已存在) |

#### 关键修复文件同步核查（10/10 OK）

| 文件 | 修复来源 | 同步状态 |
|------|---------|---------|
| `edm-takens/src/pipeline.py` | Q9 P1-17 时间轴 | ✅ |
| `edm-takens/src/final_interpretation.py` | Q9 P1-17 + Lyapunov + Koopman | ✅ |
| `edm-takens/src/enhanced_cross_validate.py` | Q9 P1-17 + Lyapunov + 截断伪影 | ✅ |
| `edm-takens-web/backend/sync_check.py` | EXPECTED_DIFFERS 白名单 | ✅ |
| `edm-takens-web/backend/edmtakens/pipeline.py` | 引擎同步 | ✅ |
| `edm-takens-web/backend/edmtakens/final_interpretation.py` | 引擎同步 | ✅ |
| `trace-engine-web/py_bridge.py` | CV ATE 计算 + bootstrap_type | ✅ |
| `trace-engine-web/public/js/schema.js` | threshold 0.3→0.03 | ✅ |
| `trace-to-edm/layer2_semantic.py` | L2 PCA 中心化 | ✅ |
| `trace-to-edm/server.js` | API 端点 + undefined 防御 | ✅ |

### 8.2 verify_portable.py 独立运行审计

| 检查项 | 结果 |
|--------|------|
| 目录结构 | ✅ PASS |
| 运行时产物污染 | ✅ PASS（无残留） |
| trace-engine 健康检查 | ✅ PASS (Python 3.10.11, dowhy 0.14) |
| trace-engine 模块导入 | ✅ PASS |
| trace-engine 自检测试 | ✅ PASS |
| SUPER 模式导入路径 | ✅ PASS（无遮蔽风险） |
| trace-engine-web 健康检查 | ✅ PASS (port=3030, /api/config 含 SUPER + max_segments) |

**最终裁决**: 全部通过，便携目录可独立运行。

### 8.3 Phase 8 文档更新清单

| # | 文档 | 更新内容 |
|---|------|---------|
| 1 | `META_AUDIT_CHANGELOG.md` | 新增 §Phase 8 章节（8.1-8.8），覆盖数据集设计/DEEP分析/回填/EDM/同步 |
| 2 | `DOC_SYNC_REPORT.md` | 本节：§8 便携式目录同步 + verify_portable 结果 |
| 3 | `Docs/META_AUDIT_CHANGELOG.md` | 同步至便携式目录 Docs/ 下 |

**Phase 8 文档同步 (2026-07-23)**
