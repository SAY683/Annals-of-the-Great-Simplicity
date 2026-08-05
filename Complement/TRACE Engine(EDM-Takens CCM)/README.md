# TRACE Engine (EDM-Takens CCM) — 便携成品目录

本目录包含四大子项目，已整理为可独立运行的成品结构：

| 项目 | 类型 | 用途 |
|------|------|------|
| `trace-engine/` | Python 因果推断引擎 | 基于 LLaMA + DoWhy + CausalLearn 的文本因果发现 |
| `trace-engine-web/` | Node.js Web 服务 | TRACE Engine 的 Web 前端 + SSE 实时日志 |
| `edm-takens/` | Python 科研级算法库 | EDM/CCM/HAVOK 数学算法 CLI（Sugihara 2012 严格契约） |
| `edm-takens-web/` | Python + JS Web 服务 | EDM-TAKENS 的 Web 前端 + 科研披露字段渲染 |
| `trace-to-edm/` | Python + JS 桥接服务 | TRACE → EDM 轨迹表转换与可视化 |

## 目录结构

```
.
├── README.md                 # 本文件
├── verify_portable.py        # 独立运行性审计脚本 (16 项契约)
├── sync_product.py           # 同步脚本 (支持 EDM-TAKENS 项目)
├── trace-engine/             # Python 因果推断引擎
│   ├── health_check.py       # 引擎健康检查
│   ├── examples/
│   │   └── counterfactual_hybrid/  # 六战士因果分析核心
│   ├── models/               # 训练好的 LLaMA 模型（SUPER 模式使用）
│   ├── tests/test_skill.py   # 引擎自检测试
│   └── date/                 # 训练/测试数据
├── trace-engine-web/         # Node.js Web 服务
│   ├── start.ps1             # 启动脚本
│   ├── stop_servers.ps1      # 停止 stale 服务
│   ├── server.js             # HTTP + SSE 服务端
│   └── public/index.html     # 前端页面
├── edm-takens/               # 科研级 EDM/CCM/HAVOK 算法库 (CLI)
│   ├── src/                  # 核心算法源码
│   │   ├── pipeline.py       # 全流程管线
│   │   ├── ccm_causality.py  # CCM 因果推断 (Sugihara 2012)
│   │   ├── sovereign_havok.py # HAVOK 动力学分析 (Brunton 2017)
│   │   ├── _numpy_edm.py     # NumPy EDM 底层实现
│   │   ├── _numeric_constants.py # 数值常量单一真相源
│   │   └── surrogate_test.py # IAAFT 替代数据检验
│   ├── tests/                # pytest 测试套件
│   ├── docs/ALGORITHM_AUDIT.md # 算法审计文档
│   ├── run_pipeline.py       # CLI 入口
│   └── run_tests.py          # 测试入口
├── edm-takens-web/           # EDM-TAKENS Web 服务
│   ├── backend/              # Python 后端 (FastAPI)
│   │   ├── api.py            # API 路由
│   │   ├── sync_check.py     # 跨项目同步检查
│   │   ├── edmtakens/        # 核心库副本 (与 edm-takens/src/ 同步)
│   │   └── services/summary_builder.py # 科研披露字段透传
│   ├── frontend/             # Vite + 原生 JS 前端
│   │   ├── src/main.js       # 前端渲染 (含 CCM 科研披露)
│   │   └── src/style.css     # 样式 (confirmatory/exploratory 视觉区分)
│   └── docs/ALGORITHM_AUDIT.md # Web 版算法审计文档
├── trace-to-edm/             # TRACE → EDM 桥接服务
├── shared/                   # 共享主题与工具
└── Models/                   # LLaMA 模型 (根级便携布局)
```

## 环境要求

- Python 3.11+（推荐 3.13）
- Node.js 18+
- 依赖包：见 `trace-engine/requirements.txt` 与 `trace-engine-web/package.json`

## 快速开始

### 1. 独立运行性审计（推荐首先执行）

```powershell
cd "TRACE Engine(EDM-Takens CCM)"
python verify_portable.py
```

审计将检查：
- 目录结构完整性
- 无运行时产物污染
- 引擎模块导入与健康状态
- 引擎自检测试
- Web 服务健康检查

### 2. 启动 Web 服务

```powershell
cd "TRACE Engine(EDM-Takens CCM)\trace-engine-web"
powershell -ExecutionPolicy Bypass -File start.ps1
```

服务将自动：
- 检测并安装 npm 依赖（首次）
- 探测可用端口（默认 3000-3020）
- 选择可写工作目录（优先脚本目录，只读时回退到 `%TEMP%\trace-engine-web-work`）

浏览器访问：http://localhost:3000

### 3. SUPER 模式（LLaMA 模型驱动）

Web 界面提供三种分析模式：

- **LIGHT**：jieba 概念图 + 简化流程（1–3 秒）
- **DEEP**：jieba 概念图 + 完整六战士深度诊断（10–60 秒）
- **SUPER**：调用 `trace-engine/models/` 下可选的三个 LLaMA 模型之一执行真正的 token-level TRACE 因果发现，再走完整六合一诊断（首次需加载模型，分析耗时视文本长度与模型规模而定）

> SUPER 模式由常驻 LLaMA Worker 处理，单线程顺序执行。模型文件较大，首次同步时自动复制到 `trace-engine/models/`。
>
> 可选模型规格（三选一）：
> - **shehui-llama**（默认，27M 参数 / ~108MB / max_position=256）：轻量高效，~800 pps，适合大规模文本快速刨析，建议显存 ≥1.5GB
> - **shenji-llama**（469M 参数 / ~1.88GB / max_position=1024）：神学/史诗古文，~10-40 pps @ RTX 3050，建议显存 ≥3.0GB
> - **shehui-llama-v4-archive**（470M 参数 / ~1.88GB / max_position=1024）：旧版归档，因果发现能力较弱，建议显存 ≥3.0GB
>
> Web 端会自动尝试 FP16 加载并在显存不足时给出提示。
>
> 参数预设：Web 界面提供 **LLAMA** 预设（`threshold=0.01, window_size=128, max_segments=3`），专为过拟合 TRACE LLaMA 模型设计。分析 Shenji 古文时可开启 `classical_mode=true`，保留 之/乎/者/也 等虚词。

### 4. 停止服务

```powershell
cd "TRACE Engine(EDM-Takens CCM)\trace-engine-web"
powershell -ExecutionPolicy Bypass -File stop_servers.ps1
```

### 5. 仅运行引擎（命令行）

```powershell
cd "TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid"
python run_cli.py --text "你的因果分析文本"
```

### 6. EDM-TAKENS CLI（科研级算法）

EDM-TAKENS 是基于 Sugihara 2012 CCM 和 Brunton 2017 HAVOK 的科研级数学算法库，
提供严格的统计推断和替代数据检验。

```powershell
cd "TRACE Engine(EDM-Takens CCM)\edm-takens"

# 运行全量测试套件 (含 HAVOK 动力学解释)
python run_tests.py

# 运行分析管线 (需准备 CSV 数据)
python run_pipeline.py --data examples/game_analysis/data/game_log.csv --target result

# 运行后, CLI 会输出科研披露字段:
#   [Guarantee] CONFIRMATORY — FDR-controlled at q=0.05 (IAAFT null, Bonferroni-corrected)
#   [Guarantee] EXPLORATORY — Exploratory FDR estimate (effect-size gated Spearman, BH)
#   [Disclaimer] 方法学免责声明
#   每对因果的 OOS/IN-SAMPLE 评估模式标注
```

### 7. EDM-TAKENS Web 服务

```powershell
cd "TRACE Engine(EDM-Takens CCM)\edm-takens-web"

# 启动后端
python run_backend.py

# 启动前端 (另一个终端)
cd frontend
npm install  # 首次
npm run dev
```

Web 界面提供 CCM 科研披露字段的完整渲染：
- **CONFIRMATORY/EXPLORATORY 徽章**：统计保证级别
- **方法学免责声明**：突出显示，引导科研用户阅读
- **收敛曲线 sparkline**：ρ vs effective_lib_size
- **OOS/IN-SAMPLE 徽章**：评估模式标注

### 8. EDM-TAKENS 跨项目同步检查

```powershell
cd "TRACE Engine(EDM-Takens CCM)\edm-takens-web\backend"
python sync_check.py
```

检查 `edm-takens/src/` 核心库与 `edm-takens-web/backend/edmtakens/` 副本的 SHA256 一致性，
以及科研披露字段的存在性。

## 环境变量

| 变量 | 说明 | 示例 |
|---|---|---|
| `TRACE_WORK_DIR` | 工作/输出目录 | `C:\trace-work` |
| `TRACE_ENGINE_SKILL_DIR` | 引擎 Skill 路径 | `...\trace-engine\examples\counterfactual_hybrid` |
| `TRACE_PYTHON_CMD` | Python 命令 | `python` 或 `python3` |
| `PORT` | Web 服务端口 | `3000` |
| `TRACE_STAGE_TIMEOUT_MS` | SUPER 模式阶段性进度看门狗超时（毫秒），无 stage 更新则判定 hang | `900000` |
| `TRACE_SRC_EDM_TAKENS` | EDM-TAKENS 核心库源码目录（sync_product.py 用） | `...\Skill\edm-takens` |
| `TRACE_SRC_EDM_TAKENS_WEB` | EDM-TAKENS Web 源码目录（sync_product.py 用） | `...\Skill\edm-takens-web` |
| `EDMTAKENS_DATA_DIR` | EDM-TAKENS Web 副本的数据目录（覆盖默认路径） | `C:\edm-data` |

## 维护说明

- 运行时产物（`outputs/`、`__pycache__/`、`*.log`）已被 `.gitignore` 排除
- 同步源目录到本成品目录请使用源端的 `sync_product.py`
- 遇到目录锁定时，运行 `trace-engine-web/stop_servers.ps1` 清理 stale 进程后再同步

### sync_product.py 自包含布局行为

本成品目录中的 `sync_product.py` 已检测到**自包含布局**（脚本所在目录即成品根，同级有 `trace-engine/` 和 `trace-engine-web/`）。在此布局下运行 `sync_product.py` 时：

- **跳过** trace-engine 和 trace-engine-web 的复制操作（避免 `src == dst` 自我覆盖）
- **执行** EDM-TAKENS 项目同步（从父级 `Skill/` 目录同步到便携目录，不存在自我覆盖风险）
- **仅执行保守清理**：删除 `.tmp_*.py` 临时测试文件、`web_*_result*.json` 遗留产物、`__pycache__/`
- **保留** `work/outputs/` 和 `work/inputs/`（用户历史数据）
- **验证**关键文件存在性（37 项核心文件 + 模型目录 + 运行时产物计数）

若需从开发布局同步到独立便携目录，请设置 `TRACE_PRODUCT_DIR` 环境变量指向目标目录：

```powershell
$env:TRACE_PRODUCT_DIR = "C:\path\to\portable"
python sync_product.py
```

### verify_portable.py 16 项审计契约

`verify_portable.py` 执行以下 16 项独立运行审计（ROUND51 契约）：

1. 目录结构（`trace-engine/` 与 `trace-engine-web/` 存在）
2. 运行时产物污染（无 `web_*_result*.json`、`test_min*.bat` 残留）
3. trace-engine 独立健康检查（`health_check.py` 通过）
4. trace-engine 核心模块导入（`counterfactual_bridge`、`six_warriors`、`presets` 等）
5. trace-engine 自检测试（`tests/test_skill.py` 通过）
6. SUPER 模式导入路径（无 `presets.py` 遮蔽风险）
7. trace-engine-web 健康检查（`/api/health` + `/api/config` 契约）
8. trace-to-edm 轨迹表契约（`bridge.py` 写入 + `app.js` 渲染 + CSS 状态色）
9. 便携式代码修缮落地（主机绑定 127.0.0.1、CCM verdict 三级语义、FCI 实现）
10. Docs 同步（`DEPENDENCY_MATRIX.md` 等 3 项关键文档）
11. EDM-TAKENS 项目同步（`edm-takens/` 与 `edm-takens-web/` 在便携目录内完整）
12. EDM-TAKENS CLI 模块导入（7 个核心算法模块可导入：pipeline/ccm/havok/edm/constants/surrogate/final_interpretation）
13. EDM-TAKENS 科研披露字段（4 个字段存在：is_strict_confirmatory/methodology_disclaimer/effective_lib_sizes/out_of_sample_used）
14. EDM-TAKENS 跨项目 sync_check（核心库与 Web 副本 SHA256 一致）
15. BAT 编码合规（无中文 + `chcp 65001`，防止 GBK 命令截断）
16. **E2E 全链路冒烟**（`smoke_e2e.py`：真实启动三服务，跑通 文本→TRACE→trace-to-edm→EDM，断言轨迹列契约 + EDM 科研披露字段；约 5-15 分钟，可用 `--no-e2e` 或 `SMOKE_E2E_OFF=1` 跳过，node/npm 缺失时 SKIP）

## 支持与故障排查

- 服务启动失败：检查 `work/server.log` 与 `work/start.log`
- Python 依赖缺失：运行 `pip install -r trace-engine/requirements.txt`
- 端口冲突：脚本会自动尝试 3000-3020，或手动设置 `PORT` 环境变量
- SUPER 模式加载模型慢/OOM：关闭其它占用显存的程序，或在环境变量中设置 `TRACE_MODEL_DTYPE=fp32` 强制 FP32；必要时缩短文本或减小 `window_size`/`max_segments`
- Shehui-LLaMA 因果边稀少：使用 `llama` 预设（`threshold=0.01`）可检出非零因果边；若仍偏少可尝试切换到 Shenji-LLaMA 或改用 DEEP 模式
- SUPER 模式 `n_significant_edges=0`：这是 LLaMA 模型对某些文本类型的因果发现能力限制（ΔNLL 值低于阈值），非 bug。详见 [ALGORITHM_AUDIT.md](trace-engine/ALGORITHM_AUDIT.md) §5.3

---

## ROUND29 修缮记录（2026-08-02）

ROUND28 遗留的 P3-P5 剩余债务已全部收口，旧档案记录已清理：

**债务收口**:
- **P3 维度5/6**: edm-takens-web 添加 `TraceIdAndCacheMiddleware`（trace_id 注入 + Cache-Control 分级）
- **P3 B-02**: 三份 Lyapunov 实现统一委托到 `estimate_lyapunov_robust`（单一真相源）
- **P3 B-01**: 新增 `test_cross_project_http.py` 跨项目调用契约测试
- **P4 维度4**: trace-engine-web `batch-delete` 限制单次上限 100 条
- **P5 B-03**: 新增 `test_six_warriors_regression.py` 代码复用契约测试

**旧档案清理**:
- `work/inputs/` 37 个历史测试输入 + `work/outputs/` 36 个任务目录 + `job_history.json`
- `edm-takens-web/jobs.sqlite`（服务启动时自动重建或回退内存存储）
- `edm-takens/src/results/` + 2 个运行时 png 图

**验证**: verify_portable.py 14/14 + portable_verify.py 61/61 + sync_check.py 20一致

详细修复经验见 [经验记忆归档.md](../经验记忆归档.md) §十二，技术细节见 [PORTABLE_TECHNICAL_GUIDE.md](PORTABLE_TECHNICAL_GUIDE.md) §2.5。
