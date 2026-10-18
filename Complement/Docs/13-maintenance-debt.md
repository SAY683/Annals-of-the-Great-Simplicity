# 13 · 维护债务与验收状态

> 本页区分“已修复”“仍可改进”“必须由作者决策”的事项，避免把长期工程债务伪装成已完成。

## 1. 当前阻塞状态

截至 2026-10-18，本项目**没有已知的 P0 / P1 功能阻塞**。

本轮最终验收：

- `trace-engine`：22 passed
- `edm-takens`：93 passed
- `edm-takens-web` 路由/列映射：5 passed
- `trace-to-edm` CSV 契约：3 passed；HTTP 路由契约：2 passed
- `verify_portable.py --no-e2e`：**16 PASS / 0 FAIL**
- `smoke_e2e.py`：**全链路通过**（15 条文本 → TRACE → trace-to-edm → EDM）
- 浏览器实测：三页面无 console error / warning；EDM 真实分析完成后 `column_mapping = null`；TRACE LIGHT 得到 12 概念 / 8 显著边 / ATE -0.2200，并显示合成 SEM 警告
- 三个 Node 项目 `npm ci` 均通过；`npm audit --omit=dev` 为 0 vulnerabilities

## 2. 本轮已完成的 P2

| 项目 | 结果 |
|---|---|
| CI | `.github/workflows/complement-ci.yml` 覆盖 Python/Node 测试、便携审计、列映射、CSV 契约、GraphRAG 数据 hash、provider 兼容层单测与隧道网关单测 |
| 浏览器回归 | 新增 `Complement/tools/browser_smoke.py`，支持三页面加载与 `--full` 真实分析；Playwright 为可选依赖 |
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

## 3. 仍需作者决策

| 项目 | 原因 |
|---|---|
| 30/40 条新闻历史实验 | 仓库内缺少完整原始输出；历史论文已加“未重新验证”横幅，不能当作当前回归结论 |

## 4. 架构级 deferred（本轮不强行拆）

| 项目 | 现状 | 建议 |
|---|---|---|
| GraphRAG provider 兼容 | 已改为运行时能力探测与回退，不再依赖 `site-packages` 补丁 | `reapply-graphrag-patches.py` 仅作旧版本排障兜底；正常查询/索引统一走 `graphrag_compat_cli.py` |
| 完整 CI E2E | 需要模型/8081/15721/本地端口专用 runner | 当前 CI 跑单测、路由契约与静态审计；E2E 作为本地发布门禁 |
| 像素级视觉回归 | 已有 Playwright smoke + 截图 | 后续可加稳定基线与截图 diff，避免动画/字体造成假阳性 |
| `trace-engine-web` 其他大文件 | `jobs.js` 约 32 KB、`app.js` 约 25 KB | 当前低于主要债务阈值，后续可按任务历史/输入控制再拆 |

## 5. 结论

当前功能链路、数据完整性、鉴权边界、可复现安装和主要大文件拆分已达到可交付状态。GraphRAG 的 provider 差异已由运行时兼容层吸收，不再要求修改 `site-packages`。剩余项主要是**历史实验复验、专用 E2E runner 和视觉基线**。