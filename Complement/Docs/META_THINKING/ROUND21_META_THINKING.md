# Round 21 — 元反思与残留盲区归档

> 创建: 2026-07-27
> 范围: 本轮 P0 修复 + 破坏性测试 + 端口管理协议的元反思
> 关联: ROUND21_ACTION_PLAN.md, ROUND21_TECH_DEBT.md
> 视角: PM + 算法工程师 + 数学家 + 统计家 + 安全审计

---

## 1. 元思考 (Meta-Thinking)

### 1.1 盲区缺陷 #1: 审计文档自身的可信度

**发现**: ROUND21_ALGORITHM_AUDIT.md 中 D-P0-2 (enhanced_cross_validate "CV"违反独立性)
的原描述是误判. 实际审计文档自身已在 §P0-3 修复建议中纠正:
"文件名/函数名误导 (cross_validate_with_safeguards 实为启发式 if-else),
应重命名为 heuristic_validation".

**反思**:
- 审计文档的"发现"和"建议"两层可能矛盾, 我最初把"发现"当作真问题修复
- 应建立"审计发现 → 二次确认 → 修复决策"的三阶段过滤
- **盲区**: 我把审计文档当作 ground truth, 没有先验证发现的真实性

**改进**: 后续处理 P1/P2 债务时, 必须先读审计文档的"修复建议"段,
再决定修复策略, 而非直接按"发现"段实施.

### 1.2 盲区缺陷 #2: 修复的边界场景

**发现**: D-P0-1 (Pearl 拓扑排序) 初次修复后, 破坏性测试 DT-1 暴露
带环图场景下抛 KeyError. 因为 predict_cf 遍历偏序 topo_order, 环中
节点不在 cf_values 中, 但 outcome 可能在环中.

**反思**:
- 我的修复"按拓扑序传播", 但没有考虑 has_cycle=True 时的兜底
- 破坏性测试 DT-1 是真正的"破坏性"测试 — 它发现的不是已有 bug, 而是
  我修复代码引入的新 bug
- **盲区**: 我假设输入是 DAG, 但 SEM 完全可能含环 (反馈回路)

**改进**: 任何拓扑排序代码必须配套环检测 + 兜底行为, 不能假设无环.

### 1.3 盲区缺陷 #3: PowerShell 字符串插值歧义

**发现**: start_all.ps1 中 `"...$($_.Exception.Message)..."` 被
PowerShell 解析器认为是变量作用域 ($_:), 报语法错误. 必须改为
先赋值再插值.

**反思**:
- PowerShell 的 `$(...)` 子表达式在含 `:` 时会与作用域前缀歧义
- 这是 PowerShell 的"暗坑", 不是逻辑错误
- **盲区**: 我以为 PS 语法检查是形式主义, 实际上发现了一个真 bug

**改进**: PS 脚本修改后必须用 Parser::ParseInput 验证, 不能依赖肉眼.

### 1.4 盲区缺陷 #4: 鉴权链的"弱/强"分级

**发现**: D-P0-4 (edm-takens-web 全端点零鉴权) 修复时, 我设计了
require_auth (强) + require_auth_optional (弱) 两级. 但反思发现,
optional 命名误导 — 实际两者逻辑相同, 只是审计语义不同.

**反思**:
- 命名应反映"读/写"而非"强/弱", 因为弱鉴权实际并不弱
- GET 端点用 require_auth_optional 是为了审计时区分, 不是为了安全降级
- **盲区**: 命名传达了错误的语义, 可能误导后续维护者

**改进**: 后续可重命名为 require_auth_read / require_auth_write,
或用 router-level dependencies 而非函数命名区分.

### 1.5 盲区缺陷 #5: 端口管理协议的"清理时机"

**发现**: start_all.ps1 启动前清理孤儿进程, 但 finally 块的清理
仍是 Stop-Process -Id (不递归). 这意味着 Ctrl+C 时虽然父进程被杀,
但 npm start 派生的 server.js 子进程可能成为新孤儿.

**反思**:
- 启动前清理是"治标", finally 块的递归清理才是"治本"
- 当前修复增加了启动前清理 + 递归子进程清理, 但 finally 块的递归清理
  仍未实现 (需要重写 $jobs 数组为"进程树")
- **盲区**: 修复了一半, 另一半留给下次, 这种"半吊子修复"违反
  project_memory 中"严禁半吊子的实现"约束

**改进**: 后续 round 应重写 finally 块, 用 Get-CimInstance
Win32_Process 递归遍历进程树, 而非依赖 $jobs 数组.

---

## 2. 残留盲区清单

### 2.1 未验证的假设

| # | 假设 | 验证方式 | 状态 |
|---|------|---------|------|
| 1 | trace-engine-web / trace-to-edm 鉴权链 OK | 审计文档说有, 未实测 | 待证实 |
| 2 | 5 项目 MCP 索引已建立 | project_memory 提到, 未验证索引完整性 | 待证实 |
| 3 | counterfactual_bridge.py L651 的 SimulationEstimand 调用 | 已修复 simulation_model.py 默认值, 该调用点未审计 | 待证实 |
| 4 | Pearl 拓扑排序在大型 SEM (V>20) 上的性能 | O(V²) 邻接矩阵遍历, 未压测 | 待证实 |
| 5 | 鉴权链对 vite 前端代理的影响 | vite 默认无 X-API-Key, 可能 401 | 待证实 |

### 2.2 未实现的设计

| # | 设计 | 原因 | 影响 |
|---|------|------|------|
| 1 | finally 块递归进程树清理 | 时间约束, 留下轮处理 | Ctrl+C 后可能留孤儿 |
| 2 | require_auth_read/write 重命名 | 避免本轮变更过激 | 命名误导风险 |
| 3 | Pearl 拓扑排序性能压测 | 无 V>20 数据集 | 大型 SEM 可能慢 |
| 4 | SimulationEstimand 在 JSON 序列化时暴露 synthetic 字段 | jobs.js export/md 未读此字段 | 用户看不到 synthetic 标记 |

### 2.3 不值得盲信的"已完成"

| # | 项 | 风险 | 验证优先级 |
|---|----|------|----------|
| 1 | trace-engine-web export/md condition_number 已暴露 | jobs.js L282-297 看似有, 但 r.execution_profile.condition_number 字段名可能与 Python 端不一致 | 高 |
| 2 | edm-takens-web export/md HAVOK condition_number 已暴露 | history.py 改了, 但 havok dict 字段名 condition_number_raw 可能不存在 | 高 |
| 3 | Pearl 拓扑排序修复 | DT-2 验证了非拓扑序正确传播, 但真实场景的 _coeff 来自 estimate_sem_from_data, 未端到端测 | 中 |
| 4 | enhanced_cross_validate 别名 | DT-5 验证了别名, 但调用方 (edm_pipeline_full) 是否还能用未验证 | 中 |
| 5 | 鉴权链 | DT-6/DT-7 验证了 require_auth 函数, 但 router-level dependencies 是否真的生效未验证 | 高 |

---

## 3. 4 角色互审

### PM 视角
- 4 P0 债务全部修复, 27/27 破坏性测试通过 — 阶段性成果
- 但残留 5 个"未验证假设" + 4 个"未实现设计", 不能宣告完成
- 端口管理协议增加了启动前清理, 但 finally 块仍是技术债

### 算法工程师视角
- Pearl 拓扑排序修复是"概念版到真实可用"的关键升级
- SimulationEstimand synthetic 标记让模拟模式不再"伪装可识别"
- 但 Pearl 大型 SEM 性能未验证, 是潜在风险

### 数学家视角
- 拓扑排序 + 环检测是图论基础, 修复方向正确
- 带环兜底用 observed 值是保守选择, 数学上不严格 (应返回 NaN 或拒绝)
- DT-2 的 ITE=0.5 验证了线性 SEM 的正确传播, 但非线性 SEM 不适用

### 统计家视角
- SimulationEstimand identifiable=False 是统计严谨性的关键修复
- 但 synthetic 字段未在 export/md 暴露, 用户仍可能看不到标记
- 建议下轮在 jobs.js export/md 中读取 r.synthetic 字段并显示

### 安全审计视角
- edm-takens-web 28 端点鉴权链已建立, 但 router-level dependencies
  的运行时生效性未端到端验证
- require_auth_optional 命名误导, 可能被维护者误以为是"可选鉴权"
- 端口清理函数 Clear-ServerProcesses 排除 vite, 符合 project_memory 约束

---

## 4. 下轮 (Round 22) 行动建议

### P0 优先
1. **端到端验证鉴权链**: 启动 edm-takens-web, 用远程 IP + 缺 key 测试
2. **验证 export/md 字段名**: 检查 r.execution_profile.condition_number
   与 Python 端字段名是否一致
3. **修复 finally 块递归清理**: 重写为进程树遍历

### P1 优先
4. **重命名 require_auth_optional**: → require_auth_read
5. **在 export/md 暴露 synthetic 字段**: jobs.js + history.py
6. **Pearl 拓扑排序性能压测**: V=20/50/100 的 SEM

### P2 改进
7. **建立审计发现过滤机制**: 审计文档的"发现"段必须二次确认
8. **PS 脚本语法检查集成**: 修改 .ps1 后自动 ParseInput 验证

---

## 5. 验收清单

- [x] 4 P0 债务修复 (D-P0-1 至 D-P0-4)
- [x] 27 项破坏性测试全部通过
- [x] 端口管理协议增强 (Clear-ServerProcesses)
- [x] 元反思 5 项盲区归档
- [x] 残留盲区清单 (5 未验证 + 4 未实现 + 5 不值得盲信)
- [ ] 端到端鉴权链验证 (待服务启动)
- [ ] 便携式同步 (待 Round 22)
