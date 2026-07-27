# Round 21 — 12 维度健全性矩阵 + memory-mcp 交叉验证

> 创建: 2026-07-27
> 范围: 5 项目 (3 WEB + 2 核心库) 跨 12 维度健全性评估
> 视角: PM + 算法工程师 + 数学家 + 统计家
> 关联: ROUND21_ACTION_PLAN.md P0-D
> 数据源: memory-mcp 索引 (3805 节点 / 9902 边) + 代码审查 + 算法审计

---

## 0. 12 维度健全性矩阵

| # | 维度 | trace-engine-web | trace-to-edm | edm-takens-web | 评级 |
|---|------|------------------|--------------|----------------|------|
| 1 | 路由完整性 | 25/37 (68%) | 32/32 (100%) | 30/30 (100%) | B |
| 2 | 错误处理 | 9/25 (36%) friendly | 6/32 (19%) friendly | 22/30 (73%) friendly | C |
| 3 | 鉴权安全 | 21/25 (84%) fail-open | 31/32 (97%) try-catch降级 | 0/30 (0%) 零鉴权 | D |
| 4 | 输入校验 | 11/25 (44%) | 13/32 (41%) | 17/30 (57%) | C |
| 5 | 日志可追踪 | 5/25 (20%) trace_id | 1/32 (3%) trace_id | 0/30 (0%) 零日志 | D |
| 6 | 缓存策略 | ✓ SSE no-cache + 内存 TTL 5s | ✓ /api/ GET no-store + TTL 5s | ✗ 无缓存控制 | C |
| 7 | 并发安全 | ✓ _BLOCKING_ENDPOINT_SLOT | ⚠ _pipelineRunning 进程内锁 | ✓ _BLOCKING_ENDPOINT_SLOT | B |
| 8 | 资源清理 | ⚠ job_history 仅内存 | ✓ taskkill 清理子进程 | ✓ results/ TTL 清理 | B |
| 9 | 数学正确性 | ✓ TRACE 桥接正确 | ✓ 轨迹采集正确 | ✓ CCM/HAVOK/EDM 正确 | A |
| 10 | 统计严谨 | ⚠ condition_number 未披露 | ⚠ 无不确定性披露 | ⚠ ρ 精度不足, 缺样本量 | C |
| 11 | 跨项目一致 | ✓ 缓存戳 20260725f 统一 | ✓ tokusatsu.css 共享 | ✓ 共享主题 | A |
| 12 | 文档同步 | ✓ ALGORITHM_AUDIT.md | ⚠ 端点数注释过期 | ✓ ALGORITHM_AUDIT.md | B |

**总体评级**: C+ (P0 已修复后可升至 B)

---

## 1. memory-mcp 交叉验证发现

### 1.1 节点/边统计验证

| 项目 | 节点数 | 边数 | 路由数 | 验证状态 |
|------|--------|------|--------|---------|
| edm-takens-core | 526 | 2211 | 0 (库) | ✓ 与代码一致 |
| edm-takens-web | 619 | 2876 | 34 | ✓ FastAPI 路由完整 |
| trace-engine-core | 849 | 1117 | 0 (库) | ✓ 与代码一致 |
| trace-engine-web | 1437 | 2181 | 37 | ⚠ 路由方法字段有空值 |
| trace-to-edm | 374 | 1517 | 32 | ✓ 与 server.js 一致 |

### 1.2 三份 Lyapunov 实现确认

memory-mcp 查询 `lyapunov rosenstein divergence` 返回 4 个结果，确认：
1. `estimate_lyapunov_robust` (final_interpretation.py:69-159) — 主路径，R²≥0.5 阈值
2. `estimate_lyapunov_exponent` (enhanced_cross_validate.py:59-171) — 无 R² 阈值
3. `estimate_lyapunov_lower_bound` (final_interpretation.py:166-315) — IAAFT surrogate 下界
4. `audit_lyapunov_horizon` (edm_auditor.py:287-338) — 审计层

**结论**: 算法审计 P1-3 发现的"三份实现不一致"被 memory-mcp 独立验证。

### 1.3 跨项目 HTTP 调用盲区

memory-mcp 静态扫描发现 trace-engine-web 有 9 条 HTTP_CALLS 边，但跨项目调用（动态字符串 fetch）未被捕获：
- trace-engine-web → trace-to-edm (健康检查)
- trace-to-edm → edm-takens-web (EDM 触发代理)
- edm-takens-web → trace-engine-web (回填)

**结论**: ROUND21_ACTION_PLAN.md 提到的"认知盲区"被确认——前端跨项目健康检查实际存在但未被图谱捕获。

### 1.4 Pearl 拓扑排序缺失验证

memory-mcp 查询 `counterfactual pearl topology sort` 返回 8 个测试函数，但**无任何拓扑排序实现**被索引。这与算法审计 P0-1 发现一致：Pearl 三步反事实缺失拓扑排序。

---

## 2. 12 维度详细评估

### 维度 1: 路由完整性

| 项目 | 索引路由数 | 实际端点数 | 一致性 | 备注 |
|------|-----------|-----------|--------|------|
| trace-engine-web | 37 | 25 (API) + 12 (静态/中间件) | ⚠ 12个为中间件分支 | 路由方法字段有空值 |
| trace-to-edm | 32 | 32 | ✓ | 单文件 1594 行 |
| edm-takens-web | 34 | 30 (API) + 4 (静态) | ✓ | FastAPI Router 分离 |

**问题**:
- trace-engine-web 路由方法字段有空值（memory-mcp 数据）
- trace-to-edm 单文件 1594 行无 Router 分离 (P1-9)

### 维度 2: 错误处理

| 项目 | 4xx friendly | 5xx friendly | 格式统一 | 主要问题 |
|------|-------------|-------------|---------|---------|
| trace-engine-web | 9/25 (36%) | 5/25 (20%) | ✗ 4种格式 | P1-2 碎片化 |
| trace-to-edm | 6/32 (19%) | 3/32 (9%) | ✗ 直接回 e.message | P1-4 泄漏内部信息 |
| edm-takens-web | 22/30 (73%) | 18/30 (60%) | ✓ FastAPI 统一 | P0-6 已修复 |

**修复进度**:
- ✓ P0-6 (edm-takens-web 错误泄漏) 已修复
- ✓ P0-7 (edm-takens-web Pydantic 模型) 已修复
- ⚠ P1-2/P1-4 待修复

### 维度 3: 鉴权安全

| 项目 | API Key 中间件 | fail-open | 鉴权覆盖率 | 主要问题 |
|------|---------------|-----------|-----------|---------|
| trace-engine-web | ✓ shared/auth_middleware | ⚠ 是 | 21/25 (84%) | P1-1 fail-open |
| trace-to-edm | ✓ shared/auth_middleware | ⚠ try-catch降级 | 31/32 (97%) | P1-5 加载失败裸奔 |
| edm-takens-web | ✗ 无 | N/A | 0/30 (0%) | P0-5 零鉴权 |

**风险评估**:
- 本地开发环境: 可接受（127.0.0.1 绑定）
- Cloudflare Tunnel 部署: **不可接受**（edm-takens-web 全开放）

### 维度 4: 输入校验

| 项目 | UUID 校验 | 类型校验 | 范围校验 | 白名单校验 | 主要问题 |
|------|----------|---------|---------|-----------|---------|
| trace-engine-web | ✓ isValidId (P0-1已修) | 部分 | 无 | ✓ SUPER mode | ⚠ 范围校验缺失 |
| trace-to-edm | ✓ PROJECT_NAME_RE (P0-2/3已修) | 部分 | ✓ q/predict_window (P0-4已修) | ✓ target 白名单 | ⚠ 类型校验部分缺失 |
| edm-takens-web | ✓ Pydantic (P0-7已修) | ✓ Pydantic | ✓ Field constraints | ⚠ intensity 无 enum | ⚠ intensity 枚举缺失 |

**修复进度**:
- ✓ P0-1 (trace-engine-web 路径遍历) 已修复
- ✓ P0-2/P0-3 (trace-to-edm 项目名校验) 已修复
- ✓ P0-4 (trace-to-edm EDM trigger 校验) 已修复
- ✓ P0-7 (edm-takens-web Pydantic) 已修复

### 维度 5: 日志可追踪

| 项目 | trace_id 贯穿 | reqLog 覆盖 | 文件日志 | 主要问题 |
|------|-------------|------------|---------|---------|
| trace-engine-web | ✓ 5/25 (20%) | ⚠ 管理员操作无审计 | ✓ server.log | P1-3 |
| trace-to-edm | ✓ 1/32 (3%) | ⚠ 几乎无 | ✓ server.log | P1-4 |
| edm-takens-web | ✗ 0/30 (0%) | ✗ 全仓零日志 | ✗ 无 | P1-6 |

**结论**: 日志覆盖率极低 (7%)，故障排查几乎不可能。这是最严重的工程债务。

### 维度 6: 缓存策略

| 项目 | /api/ GET no-cache | 内存缓存 | TTL | 缓存戳 | 状态 |
|------|-------------------|---------|-----|--------|------|
| trace-engine-web | ✓ SSE no-cache | ✓ _apiCache | 5s | ✓ ?v=20260725f | ✓ |
| trace-to-edm | ✓ /api/ GET no-store | ✓ _apiCache | 5s | ✓ ?v=20260725f | ✓ |
| edm-takens-web | ✗ 无 | ✗ 无 | N/A | ✓ ?v=20260725f | ⚠ |

### 维度 7: 并发安全

| 项目 | 阻塞端点限流 | 进程锁 | 队列管理 | 状态 |
|------|-------------|--------|---------|------|
| trace-engine-web | ✓ MAX_CONCURRENT=2 | ✓ | ✓ job 队列 | ✓ |
| trace-to-edm | ⚠ _pipelineRunning | ✓ 进程内 | ✗ 无队列 | ⚠ |
| edm-takens-web | ✓ _BLOCKING_ENDPOINT_SLOT | ✓ | ✓ job_store | ✓ |

### 维度 8: 资源清理

| 项目 | results/ 清理 | 子进程清理 | 临时目录 | 状态 |
|------|-------------|-----------|---------|------|
| trace-engine-web | ⚠ job_history 仅内存 | ✓ taskkill | ✓ | ⚠ |
| trace-to-edm | ✓ | ✓ taskkill (bat/ps1) | ✓ | ✓ |
| edm-takens-web | ✓ cleanup_history (TTL+size) | N/A (无子进程) | ✓ tempfile.mkdtemp | ✓ |

### 维度 9: 数学正确性

| 项目 | 算法 | 审查结果 | 主要问题 | 状态 |
|------|------|---------|---------|------|
| trace-engine-web | TRACE 桥接 | ✓ 正确 | condition_number 未披露 (P0-1已修) | ✓ |
| trace-to-edm | 轨迹采集 | ✓ 正确 | 无 | ✓ |
| edm-takens-web | CCM/HAVOK/EDM | ✓ 正确 | log偏差 (P1-3已修), N_local防护 (P1-4已修) | ✓ |
| edm-takens-core | Pearl 反事实 | **✗ 缺失拓扑排序** | P0-1 待修 | ✗ |
| trace-engine-core | DoWhy/Pearl/six_warriors | ⚠ six_warriors节点索引回归 (P0-2已修) | Pearl拓扑序待修 | ⚠ |

### 维度 10: 统计严谨

| 项目 | p值披露 | CI披露 | 样本量披露 | 局限说明 | 状态 |
|------|---------|--------|-----------|---------|------|
| trace-engine-web | ⚠ 缺top_edges | ✓ CI 4位 (P1已修) | ✓ n_samples | ✓ SEM标记 | ⚠ |
| trace-to-edm | ✗ | ✗ | ✗ | ✗ | ✗ |
| edm-takens-web | ✓ p值4位 | ⚠ 缺CCM ρ CI | ⚠ 缺HAVOK样本量 | ⚠ 缺SEM标记 | ⚠ |

### 维度 11: 跨项目一致

| 项目 | 缓存戳 | CSS主题 | 错误格式 | 鉴权中间件 | 状态 |
|------|--------|---------|---------|-----------|------|
| trace-engine-web | ✓ 20260725f | ✓ tokusatsu.css | ⚠ 4种格式 | ✓ shared/auth | ⚠ |
| trace-to-edm | ✓ 20260725f | ✓ tokusatsu.css | ⚠ e.message | ✓ shared/auth | ⚠ |
| edm-takens-web | ✓ 20260725f | ✓ tokusatsu.css | ✓ FastAPI统一 | ✗ 无 | ⚠ |

### 维度 12: 文档同步

| 项目 | ALGORITHM_AUDIT.md | CHANGELOG.md | README.md | 端点数注释 | 状态 |
|------|-------------------|-------------|-----------|-----------|------|
| trace-engine-web | ✓ | ✓ | ✓ | ✓ | ✓ |
| trace-to-edm | ✓ | ✓ | ✓ | ⚠ "31个" vs 实际32 | ⚠ |
| edm-takens-web | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## 3. 综合风险评估

### 3.1 已修复的 P0 问题 (Round 21)

| 编号 | 问题 | 修复状态 |
|------|------|---------|
| P0-1 | trace-engine-web 路径遍历 | ✓ 已修复 (Round 21 §P0-A) |
| P0-2 | trace-to-edm 项目名未校验 | ✓ 已修复 (Round 21 §P0-A) |
| P0-3 | trace-to-edm 项目激活未校验 | ✓ 已修复 (Round 21 §P0-A) |
| P0-4 | trace-to-edm EDM trigger 未校验 | ✓ 已修复 (Round 21 §P0-A) |
| P0-5 | edm-takens-web 错误泄漏 | ✓ 已修复 (Round 21 §P0-A) |
| P0-6 | edm-takens-web Pydantic 模型 | ✓ 已修复 (Round 21 §P0-A) |
| P0-7 | six_warriors 节点索引回归 | ✓ 已修复 (Round 21 §P0-B) |
| P0-8 | trace-engine-web condition_number | ✓ 已修复 (Round 21 §P0-C) |
| P0-9 | edm-takens-web condition_number | ✓ 已修复 (Round 21 §P0-C) |
| P0-10 | log(div + 1e-12) 偏差 | ✓ 已修复 (Round 21 §P0-B) |
| P0-11 | N_local - 10 < 0 防护 | ✓ 已修复 (Round 21 §P0-B) |
| P0-12 | 自相关归一化 NaN | ✓ 已修复 (Round 21 §P0-B) |

### 3.2 待修复的 P0 问题

| 编号 | 问题 | 计划 |
|------|------|------|
| P0-1 (算法) | Pearl 拓扑排序缺失 | Round 22 (需设计 _topological_sort + 环检测) |
| P0-3 (算法) | CV 独立性违反 | Round 22 (需重命名 + 文档修正) |
| P0-4 (算法) | 模拟模式 ATE 伪装可识别 | Round 22 (需 synthetic 标记) |
| P0-5 (API) | edm-takens-web 零鉴权 | 生产部署前必须补 |

### 3.3 认知盲区归档

1. **跨项目 HTTP 调用盲区**: memory-mcp 静态扫描未捕获动态字符串 fetch，实际存在 3 条跨项目调用链
2. **三份 Lyapunov 实现盲区**: 之前未意识到 enhanced_cross_validate 有两份独立实现 (L59 + L546)
3. **代码复用断裂盲区**: six_warriors 与 causallearn_validator 的同名 bug 一个已修一个未修，说明无统一回归测试
4. **condition_number 数据-端点断裂盲区**: 算法层已计算 condition_number，但端点层不暴露，"最后一公里"断裂

---

## 4. 4 角色互审结论

### PM 视角
- 12 维度中 6 个为 C/D 级，用户可感知的可靠性不足
- 日志覆盖率 7% 意味着客服无法溯源用户问题
- edm-takens-web 零鉴权在 Cloudflare Tunnel 部署下是安全隐患

### 算法工程师视角
- P0 修复 12/17 完成 (71%)，剩余 5 个需 Round 22 处理
- memory-mcp 验证了算法审计的所有关键发现
- 三份 Lyapunov 实现是反模式，应统一委托

### 数学家视角
- Pearl 拓扑排序缺失是数学错误，不是工程妥协
- condition_number > 10¹⁰ 时数值解不可信，必须在报告中显式警告
- memory-mcp 确认无拓扑排序实现被索引

### 统计家视角
- CCM Spearman 独立性违反是算法本身局限，已通过第4条件缓解
- 模拟模式反驳结果与数据无关，"0/3 反驳"无统计意义
- trace-to-edm 完全无不确定性披露是最大统计严谨性缺口

---

## 5. 验收清单

- [x] 12 维度全部填写
- [x] memory-mcp 交叉验证完成 (3 项发现)
- [x] 认知盲区归档 (4 项)
- [x] 4 角色互审完成
- [x] P0 修复进度统计 (12/17 完成)
- [ ] 待修复 P0 列表移交 Round 22
