# 13 · 维护债务与验收状态

> 本页区分“已修复”“仍可改进”“必须由作者决策”的事项，避免把长期工程债务伪装成已完成。

## 1. 当前阻塞状态

截至 2026-10-18，本项目**没有已知的 P0 / P1 功能阻塞**。

本轮最终验收：

- `trace-engine`：22 passed
- `edm-takens`：96 passed
- `edm-takens-web` 路由/列映射/归档：7 passed
- `trace-to-edm` Python 契约：6 passed；HTTP 路由契约：2 passed
- `verify_portable.py --no-e2e`：**16 PASS / 0 FAIL**
- `smoke_e2e.py`：**全链路通过**（15 条文本 → TRACE → trace-to-edm → EDM）
- 浏览器实测：三页面无 console error / warning；EDM 真实分析完成后 `column_mapping = null`；TRACE LIGHT 得到 12 概念 / 8 显著边 / ATE -0.2200，并显示合成 SEM 警告
- 三个 Node 项目 `npm ci` 均通过；`npm audit --omit=dev` 为 0 vulnerabilities

## 2. 本轮已完成的 P2

| 项目 | 结果 |
|---|---|
| CI | `.github/workflows/complement-ci.yml` 覆盖 Python/Node 测试、便携审计、列映射、CSV 契约、GraphRAG 数据 hash、provider 兼容层单测与隧道网关单测 |
| 浏览器回归 | `Complement/tools/browser_smoke.py` 支持三页面加载与 `--full` 真实分析；本轮另完成 TRACE LIGHT/DEEP/SUPER、Bridge 回填管线与 EDM 触发、EDM 上传/质量曲线/历史导出/归档恢复/对比/删除全流程浏览器实测，修复项复测后 console error/warning 均为 0 |
| CSV 导入 | 修复文本 CSV 导入的逗号/引号解析与 Windows 命令行长度问题；CSV 在 Python 端用 `csv.DictReader` 解析，`pyDS` 改由 stdin 传递 JSON；40 行 `news_40_csv_input.csv` 导入实测通过 |
| Bridge EDM | 修复 EDM 任务成功状态 `done` 未被前端识别、180 秒过早超时、轨迹目标列硬编码 `result` 的问题；16 行回填链路得到 `pipeline=ok / cross_validation=ok / interpretation=ok` |
| Bridge 数据隔离 | 修复 Bridge 触发 EDM 时覆盖固定 `edm-takens-web/data/narrative_meta_trajectories.csv` 的问题；改为 `trace_to_edm_<project>.csv` 项目隔离文件名 |
| 归档回看 | 新增归档图片直读端点，归档任务无需先恢复到 `results/` 即可完整显示图片；补充路径穿越与 zip 读取测试 |
| 模型平台授权 | ModelScope 三个自训练模型的 README front matter 与平台 `License` 字段已同步为 MIT，并通过公开 API 核验 |
| 运行时目录 | 忽略 `edm-takens-web/results/`、归档 zip、Bridge 生成的 EDM 临时数据集与 `projects/_index.json`；`clean_runtime.ps1` 可清理空脚手架，`trace-to-edm/data/outputs` 在使用时自动重建 |
| EDM 列映射 | 修复 `deaths/damage` 位置式互换；规范列保留、冲突列备份、非规范列映射到未占用别名 |
| CSV 契约 | 统一为 **89 列**（Meta 7 + L1 30 + L2 4 + L3 48），新增 `trace_data_source` 并补测试 |
| GraphRAG 数据 | `data_version.json`、计数/hash 一致性、LanceDB 向量/parquet ID 同步、U+FFFD、别名 schema 均由 `verify-env.py` 校验 |
| GraphRAG 服务门控 | 8081/15721 默认仅告警；`--require-services` 用于查询前严格门控；`--no-services` 用于 CI/静态检查 |
| GraphRAG provider 兼容 | 新增运行时能力探测/回退；覆盖 sync/async/batch/thread-pool，统一 JSON 容错；6 个单测通过，真实 GraphRAG mock completion 验证通过；不再需要修改 site-packages |
| 网页字体与长文本 | 1440/1280/1024/390/320 宽度与 100%/125%/150% 字体缩放实测；修复移动端缩放按钮、参数网格、任务历史、状态卡、Bridge 数据源/标题、EDM 摘要/历史/归档的长文本溢出；长中文与无空格拉丁串均不撑破视口 |
| 模型路径 | `Models/` 与历史 `models/` 大小写兼容；`verify_models.py`、`sync_product.py`、`_config.py`、`trace-to-edm/config.py` 同步修正 |
| 模型授权 | 作者确认自训练模型采用 MIT；新增 `MODEL_LICENSE.md` 与 `trace-engine/models/LICENSE`，并同步 `Docs/10-models.md` 与根 README |
| 隧道安全 | 登录跳转限制为站内路径；畸形 Cookie 不再崩溃；支持 https upstream；token 要求 ≥32 字符 |
| 依赖卫生 | 移除 `trace-to-edm` 未使用的 `multer`；升级 `trace-engine-web` 的 `multer` 与 `uuid`，审计归零 |
| `trace-to-edm` 路由 | `server.js` 从约 2487 行降到 46 行；新增 `src/app.js`、7 个 route 模块、配置/日志/缓存/Python/任务/数据集/轨迹服务，并补 HTTP 契约测试 |
| `edm-takens-web` 历史路由 | `history.py` 从 1464 行降到 108 行；拆出 archives/exports 路由、schemas、history/archive/export 服务与 task repository，并补 5 个路由测试 |
| `render.js` | 从 1641 行降到 556 行；拓扑、矩阵、3D/2D、切换器拆为独立浏览器脚本，版本号更新防止旧缓存 |
| 算法副本 | 删除 `edm-takens-web/backend/edmtakens/` 副本；Web 直接导入 `edm-takens/src` 唯一真源，`sync_check.py` 改为拒绝副本复活 |
| 发布卫生 | `check_docs.py` 校验 85 条相对链接；`build_release.ps1` fail-closed 检查 718 个 ZIP 条目，拒绝运行状态、密钥与本地模型；源码包 115.53 MB，SHA256 manifest 一致 |
| 真实新闻试点 | 新增 `smoke_e2e.py --corpus-dir`；15 篇微信公众号公开文章完成 LIGHT→89 列轨迹→EDM，15/15 TRACE 成功；N=15 时 CCM 0/6 显著、HAVOK 退化，作为“可运行但不可过度解释”的实证边界 |
| TRACE 失败显式化 | `result.success=false` 不再被当作成功；E2E 要求全部轨迹行 `trace_status=OK/PARTIAL`，并用当前 Python 解释器注入 `TRACE_PYTHON_CMD`，避免误用缺依赖的 PATH Python |
| 运行速度观测 | 优化前 15 篇长文 LIGHT 文本阶段约 2.6 分钟；加入常驻 worker、内容缓存与 L1 预取后，warm run 约 30–45 秒，首篇 L2/L3 模型加载仍约 23–30 秒，EDM 约 50–70 秒 |
| 结构化性能优化 | `py_bridge_worker.py` 复用 Python/skill 导入；TRACE/EDM/语义嵌入三类内容缓存；`TRACE_PREFETCH_WORKERS` 有界预取；N<30 exploratory 时跳过不可靠的 CCM 批次；`edm_only.py` 避免 full bridge 冷启动 |`n| 推理内存回退 | CUDA 显存不足时自动转 CPU FP32；15 篇语料语义嵌入冷预热约 32 秒，缓存命中后单条约 5ms。避免了 4 GiB 显卡 FP16 溢出的数量级退化 |

## 3. 仍需作者决策

| 项目 | 原因 |
|---|---|
| 30/40 条新闻历史实验 | 仓库内缺少完整原始输出；历史论文已加“未重新验证”横幅，不能当作当前回归结论 |

## 4. 架构级 deferred（本轮不强行拆）

| 项目 | 现状 | 建议 |
|---|---|---|
| GraphRAG provider 兼容 | 已改为运行时能力探测与回退，不再依赖 `site-packages` 补丁 | `reapply-graphrag-patches.py` 仅作旧版本排障兜底；正常查询/索引统一走 `graphrag_compat_cli.py` |
| 完整 CI E2E | 需要模型/8081/15721/本地端口专用 runner | 当前 CI 跑单测、路由契约与静态审计；E2E 作为本地发布门禁 |
| 全文本 40 行 L3 管线耗时 | CPU 环境下逐条 L3 语义投影可能达到 20 分钟以上；回填路径约数秒至数分钟 | 发布文档已给出回填优先策略；后续可增加并行 L3 与更准确的 ETA |
| 像素级视觉回归 | 已有 Playwright smoke + 截图 | 后续可加稳定基线与截图 diff，避免动画/字体造成假阳性 |
| `trace-engine-web` 其他大文件 | `jobs.js` 约 32 KB、`app.js` 约 25 KB | 当前低于主要债务阈值，后续可按任务历史/输入控制再拆 |

## 5. 结论

当前功能链路、数据完整性、鉴权边界、可复现安装和主要大文件拆分已达到可交付状态。GraphRAG 的 provider 差异已由运行时兼容层吸收，不再要求修改 `site-packages`。剩余项主要是**历史实验复验、专用 E2E runner 和视觉基线**。
