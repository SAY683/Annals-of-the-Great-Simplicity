# ROUND 30 — 元经验反思与 P1 修缮归档

> 生成时间: 2026-08-03
> 视角: 元认知 (Meta-Cognitive) + 交叉验证 (Cross-Verification) + 盲区承认 (Blind-Spot Acknowledgment)
> 范围: ROUND29 遗留 P1 修缮 + summary 误报检测 + 文档断裂修复 + 鉴权盲区
> 关联文档: `ROUND28_META_THINKING.md`, `PORTABLE_TECHNICAL_GUIDE.md`, `经验记忆归档.md`

---

## 第一部分: 盲区承认 — 本轮发现的关键盲区

### 1.1 盲区 1: summary 误报 edm-takens-web MCP 鉴权已加

**病灶描述**:
ROUND29 的 summary 声称"edm-takens-web/backend/mcp.py 的 mcp_endpoint 添加了 Depends(require_auth)"。实际交叉验证发现：
- `mcp.py:138` 的 `@router.post("/mcp")` 无 `dependencies` 参数
- `mcp.py:187` 的 `@router.get("/mcp")` 无 `dependencies` 参数
- `api.py:280` 的 `app.include_router(create_mcp_router(8000))` 未传 dependencies

**根因分析**:
1. summary 生成时未实际读取 mcp.py 源码，仅基于"应该加了"的假设
2. 缺乏交叉验证机制 —— 单一来源（summary）被信任为真
3. ROUND29 可能在其他位置添加了鉴权（如全局中间件），但未落实到 MCP 路由声明

**元思考**:
这暴露了"声明-实现鸿沟"的变体：**summary-实现鸿沟**。summary 作为上下文摘要，其声明被后续工作误认为已落地的事实。用户明确警告"对于自己的上下文的项目进展，必须保持警惕的怀疑，除非得到了多方面的交叉确认，否则不应当直接确认"。本轮验证证明了这一警告的必要性。

**实践处理**:
- 所有 P1 修缮项必须通过 Grep/Read 交叉验证源码，不信任 summary 声明
- 验证标准：`@router.post` / `@router.get` 必须显式声明 `dependencies=[Depends(require_auth)]`
- 修复后立即用 `python -m py_compile` 验证语法，用 SHA256 验证源/副本一致

### 1.2 盲区 2: PORTABLE_TECHNICAL_GUIDE.md 丢失未检测

**病灶描述**:
`sync_product.py:remove_old_root_after_migration()` 的 `keep_root` 白名单包含 `PORTABLE_TECHNICAL_GUIDE.md`，但该文件实际不存在。白名单只能防止后续被删，无法恢复已丢失的文件。

**根因分析**:
1. 原版 sync_product.py 在添加白名单保护前已误删该文件
2. `verify_portable.py:check_docs_sync` 只校验 `Docs/` 目录下的 3 项文档，未校验便携目录根的关键文档
3. README.md 第 263 行引用了该文件，但文件不存在 —— 文档断裂未被检测

**元思考**:
这是"白名单空保护"反模式 —— 保护机制存在但保护对象已丢失。检测方法只检查"是否会删"，不检查"是否存在"。完整的防护应该是：白名单保护 + 存在性校验。

**实践处理**:
- 重建 PORTABLE_TECHNICAL_GUIDE.md（322 行，涵盖便携契约/启动顺序/14项验证/MCP协议/故障排查）
- 扩展 `check_docs_sync` 校验便携目录根 4 项关键文档
- 所有引用关系（README → PORTABLE_TECHNICAL_GUIDE）必须双向校验

### 1.3 盲区 3: jobs.sqlite 运行时污染未排除

**病灶描述**:
`edm-takens-web/backend/job_store.py:206` 默认将 `jobs.sqlite` 写入 `edm-takens-web/` 根目录。`sync_product.py` 的 `edm_takens_web_ignore` 未排除 SQLite 文件，导致：
1. 同步时 `jobs.sqlite` 被复制到便携目录
2. 携带旧任务历史与可能的敏感数据
3. 多次同步后便携目录累积陈旧数据库

**根因分析**:
1. `edm_takens_web_ignore` 只排除了 `__pycache__`、`node_modules`、`outputs` 等常见产物，遗漏了 SQLite 数据库
2. `job_store.py` 的默认 `db_path` 是项目根，而非独立的 `data/` 或 `var/` 目录
3. `verify_portable.py:check_no_runtime_artifacts` 只检查 `trace-engine-web`，未覆盖 `edm-takens-web`

**元思考**:
运行时产物防护需要"全量普查" —— 任何由应用运行时创建的非代码文件都应排除。SQLite 数据库、日志文件、临时缓存都属于此类。原版只防护了"已知"产物，未防护"可能"产物。

**实践处理**:
- `edm_takens_web_ignore` 新增 `jobs.sqlite`、`*.sqlite`、`*.sqlite-journal`、`*.sqlite-wal`、`*.sqlite-shm`、`*.db`
- `check_no_runtime_artifacts` 扩展覆盖 `edm-takens-web/` 的 SQLite 污染检查
- 建议后续将 `job_store.py` 的默认 `db_path` 改为 `data/jobs.sqlite`（需评估兼容性）

### 1.4 盲区 4: 开发源码与便携副本未同步修改

**病灶描述**:
便携目录的 `edm-takens-web/backend/mcp.py` 修复后，开发源码 `Skill/edm-takens-web/backend/mcp.py` 仍是旧版本。下次 `sync_product.py` 运行时会用开发源码覆盖便携副本，导致修复丢失。

**根因分析**:
1. 修缮时只关注便携目录（当前工作目录），忽略了开发源码
2. `sync_product.py` 在自包含布局下从 `_SCRIPT_DIR.parent / 'Skill'` 同步 EDM-TAKENS 项目
3. 缺乏"源/副本一致性"的修缮纪律

**元思考**:
这是"单点修复"反模式 —— 只修一处，不修源头。用户原则"应修尽修"要求所有副本同步修改。对于 sync_product.py 维护的项目，必须同时修改开发源码和便携副本。

**实践处理**:
- 修复后立即用 SHA256 验证源/副本一致（本轮验证: `180b252a...` 一致）
- 修缮流程增加"源/副本同步检查"步骤
- 考虑建立"源优先"修缮纪律：先改开发源码，再 sync 到便携目录

---

## 第二部分: P1 修缮清单 — 严谨记录

### 2.1 修缮项矩阵

| # | 修缮项 | 文件 | 行号 | 病灶 | 修复 | 验证 |
|---|---|---|---|---|---|---|
| 1 | sync_product.py 白名单 | sync_product.py | 219-221 | 误删 PORTABLE_TECHNICAL_GUIDE.md 等 3 文件 | keep_root 新增 3 项 | Grep 确认 |
| 2 | server.js body limit | trace-to-edm/server.js | 203-204 | 2mb 太小，长文本 500 | 恢复 20mb | Grep 确认 |
| 3 | 缓存戳统一 | 3 个 index.html | — | 缓存戳不一致 | 统一 20260803a | Grep 确认 3 文件 |
| 4 | jobs.sqlite 排除 | sync_product.py | 111-117 | 未排除 SQLite 文件 | 新增 6 个排除模式 | py_compile 通过 |
| 5 | 污染检查扩展 | verify_portable.py | 74-94 | 未覆盖 edm-takens-web | 扩展 SQLite/outputs/log 检查 | py_compile 通过 |
| 6 | PORTABLE_TECHNICAL_GUIDE.md 重建 | 便携目录根 | — | 文件丢失 | 重建 322 行 | check_docs_sync 通过 |
| 7 | edm-takens-web MCP 鉴权 | mcp.py | 162, 222 | 未加 Depends(require_auth) | POST/GET 均加鉴权 | py_compile + SHA256 |
| 8 | MCP 鉴权头透传 | mcp.py | 170-177, 91-105 | 未透传 X-API-Key | fwd_headers 透传 | py_compile 通过 |
| 9 | 开发源码同步 | Skill/edm-takens-web/backend/mcp.py | — | 便携副本修复后源码未同步 | 全文覆盖 | SHA256 一致 |
| 10 | check_docs_sync 扩展 | verify_portable.py | 504-519 | 未校验便携根文档 | 新增 4 项校验 | 函数验证通过 |

### 2.2 验证结果

```
sync_check.py:        20 一致 / 2 预期差异 / 0 不一致 / 0 副本缺失
health_check.py:      success=true, status=healthy, 5 核心依赖可用
verify_portable.py:   14 PASS / 0 FAIL / 14 项 (ROUND28 14项契约)
check_docs_sync:      Docs/ 3 项 + 便携根 4 项 = 7 项齐全
源/副本 SHA256:        180b252a... (mcp.py 源=副本)
```

---

## 第三部分: 元思考 — 修缮过程的系统性反思

### 3.1 反复出现的问题模式

回顾 ROUND21-ROUND30 的 10 轮迭代，以下问题模式反复出现：

| 模式 | 出现轮次 | 根因 | 本轮是否再现 |
|---|---|---|---|
| 声明-实现鸿沟 | R21, R26, R28 | summary 声明 ≠ 代码实现 | ✓ (MCP 鉴权误报) |
| 跨文件失同步 | R26, R28 | 源/副本修改不同步 | ✓ (mcp.py 源/副本) |
| 白名单空保护 | R28 | 保护机制存在但对象丢失 | ✓ (PORTABLE_TECHNICAL_GUIDE.md) |
| 运行时产物污染 | R28 | ignore 模式不全 | ✓ (jobs.sqlite) |
| 文档断裂 | R26, R28 | 引用关系未双向校验 | ✓ (README→GUIDE) |

### 3.2 为何问题层出不穷

1. **"修缮-验证"闭环不完整**: 修缮后只验证语法，不验证语义。py_compile 通过不代表功能正确。

2. **"单源信任"风险**: summary 作为唯一信息源被信任，缺乏交叉验证。用户警告"除非得到了多方面的交叉确认，否则不应当直接确认"。

3. **"局部修复"惯性**: 只修当前可见的病灶，不追踪同类模式。修了 mcp.py 的鉴权，但没立即检查其他 MCP 端点（trace-engine-web、trace-to-edm）。

4. **"白名单幻觉"**: 认为加了白名单就安全了，不检查白名单保护的对象是否存在。

### 3.3 解药：缜密修缮纪律

| 纪律 | 实践 |
|---|---|
| 交叉验证 | 所有 summary 声明必须通过 Grep/Read 验证源码 |
| 源/副本同步 | 修缮后立即同步开发源码，用 SHA256 验证一致 |
| 双向校验 | 文档引用关系必须双向校验（A 引用 B → B 必须存在） |
| 全量普查 | 运行时产物防护覆盖所有可能的文件类型（.sqlite/.log/.db/.tmp） |
| 闭环验证 | 修缮→语法检查→语义验证→契约验证→源/副本一致 |

---

## 第四部分: 待推进事项

### 4.1 P2-P5 剩余债务

- [ ] 性能优化：SUPER 模式首次加载耗时优化
- [ ] 文档补全：部分 ALGORITHM_AUDIT.md 的旧数值修正
- [ ] 注释完善：核心算法模块的数学公式注释

### 4.2 端到端测试

- [ ] 阶段5: 3 Web 漫游 + 界面排版审视（紧凑/特摄美学/无突兀白色）
- [ ] 阶段6: edm-takens CLI + trace-engine CLI（LIGHT/DEEP/SUPER）真实数据流测试
- [ ] 阶段7: 算法/数学家视角审计（EDM/HAVOK/CCM 数学正确性 + 统计严谨性）

### 4.3 便携目录最终移植

- [ ] 阶段8: 同步 5 项目到 `G:\git\...\Complement`（Models 严禁改动）
- [ ] 技术文档更新（路由/设计修缮同步）

---

## 第五部分: 归档元数据

| 字段 | 值 |
|---|---|
| 轮次 | ROUND30 |
| 日期 | 2026-08-03 |
| 修缮项数 | 10 |
| 验证结果 | 14/14 PASS + 7/7 文档齐全 + 源/副本 SHA256 一致 |
| 关键盲区 | summary 误报、白名单空保护、运行时产物遗漏、源/副本失同步 |
| 元思考核心 | 交叉验证 > 单源信任；存在性校验 > 白名单保护；全量普查 > 已知防护 |

---

*本文档由 ROUND30 P1 修缮生成。所有引用路径与行号均来自实际代码交叉验证，未经叙事化修饰。*
