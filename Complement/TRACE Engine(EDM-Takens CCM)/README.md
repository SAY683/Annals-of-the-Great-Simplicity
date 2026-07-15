# TRACE Engine (EDM-Takens CCM) — 便携成品目录

本目录包含 `trace-engine`（因果推断引擎）与 `trace-engine-web`（Web 服务）两个子项目，已整理为可独立运行的成品结构。

## 目录结构

```
.
├── README.md                 # 本文件
├── verify_portable.py        # 独立运行性审计脚本
├── trace-engine/             # Python 因果推断引擎
│   ├── health_check.py       # 引擎健康检查
│   ├── examples/
│   │   └── counterfactual_hybrid/  # 六战士因果分析核心
│   ├── models/               # 训练好的 LLaMA 模型（SUPER 模式使用）
│   ├── tests/test_skill.py   # 引擎自检测试
│   └── date/                 # 训练/测试数据
└── trace-engine-web/         # Node.js Web 服务
    ├── start.ps1             # 启动脚本
    ├── stop_servers.ps1      # 停止 stale 服务
    ├── server.js             # HTTP + SSE 服务端
    └── public/index.html     # 前端页面
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
- **SUPER**：调用 `trace-engine/models/shehui-llama` 执行真正的 token-level TRACE 因果发现，再走完整六合一诊断（首次需加载模型，分析耗时视文本长度而定）

> SUPER 模式由常驻 LLaMA Worker 处理，单线程顺序执行。模型文件较大，首次同步时自动复制到 `trace-engine/models/`。
>
> 模型规格：Shehui-LLaMA 与 Shenji-LLaMA 均为约 **470M 参数 / ~1.8GB** 的 safetensors 模型。建议在 NVIDIA 显卡空闲显存 **≥3.0GB** 的设备上运行；Web 端会自动尝试 FP16 加载并在显存不足时给出提示。
>
> 参数预设：Web 界面提供 **LLAMA** 预设（`threshold=0.01, window_size=128, max_segments=3`），专为 V4 过拟合模型设计。分析 Shenji 古文时可开启 `classical_mode=true`，保留 之/乎/者/也 等虚词。

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

## 环境变量

| 变量 | 说明 | 示例 |
|---|---|---|
| `TRACE_WORK_DIR` | 工作/输出目录 | `C:\trace-work` |
| `TRACE_ENGINE_SKILL_DIR` | 引擎 Skill 路径 | `...\trace-engine\examples\counterfactual_hybrid` |
| `TRACE_PYTHON_CMD` | Python 命令 | `python` 或 `python3` |
| `PORT` | Web 服务端口 | `3000` |

## 维护说明

- 运行时产物（`outputs/`、`__pycache__/`、`*.log`）已被 `.gitignore` 排除
- 同步源目录到本成品目录请使用源端的 `sync_product.py`
- 遇到目录锁定时，运行 `trace-engine-web/stop_servers.ps1` 清理 stale 进程后再同步

## 支持与故障排查

- 服务启动失败：检查 `work/server.log` 与 `work/start.log`
- Python 依赖缺失：运行 `pip install -r trace-engine/requirements.txt`
- 端口冲突：脚本会自动尝试 3000-3020，或手动设置 `PORT` 环境变量
- SUPER 模式加载模型慢/OOM：关闭其它占用显存的程序，或在环境变量中设置 `TRACE_MODEL_DTYPE=fp32` 强制 FP32；必要时缩短文本或减小 `window_size`/`max_segments`
- Shehui-LLaMA 输出 0 条因果边：这是当前模型权重对 TRACE mask 干预不敏感导致，可尝试切换到 Shenji-LLaMA 或改用 DEEP 模式；代码与阈值本身无异常
