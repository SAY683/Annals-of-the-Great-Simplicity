# 11 · 依赖、解释器与可复现性

## 1. 运行时基线

本机已验证组合：

| 组件 | 版本 |
|---|---|
| Python（完整） | 3.13.2（`G:\Python\python.exe`） |
| Python（默认 PATH 示例） | 3.12.13（Anaconda，可能缺 TRACE 依赖） |
| Node.js | 24.21.0 |
| npm | 11.17.0 |
| graphrag | 3.1.1 |
| lancedb | 0.34.0 |
| mcp | 2.0.0 |
| dowhy | 0.14 |
| causal-learn | 0.1.4.8 |
| pyEDM | 2.5.0 |

## 2. Python 依赖分层

| 层 | 必需模块 | 说明 |
|---|---|---|
| EDM 核心 | `numpy`, `pandas`, `scipy`, `scikit-learn`, `pyEDM` | `pyEDM` 缺失时可回退 numpy 实现，但精度/速度下降 |
| TRACE LIGHT/DEEP | `jieba`, `dowhy`, import `causallearn`（PyPI 包名 `causal-learn`） | 缺 `jieba` 会退化为低质量切分；缺 DoWhy 会走 SimulationModel |
| SUPER | `torch`, `transformers` + 模型文件 | 见 `10-models.md` |
| EDM Web | `fastapi`, `uvicorn`, `python-multipart` | 后端 |
| GraphRAG | `graphrag`, `lancedb`, `pandas`, `pyarrow`, `mcp`, `openai`, `tiktoken` | 见 GraphRAG `requirements.txt` |

## 3. 解释器选择

`start_all.ps1` 与 `trace-engine-web/start.ps1` 会通过 `shared/python_env.ps1` 自动探测：

1. `TRACE_PYTHON_CMD`
2. `EDM_PYTHON_CMD`
3. `GRAPHRAG_PYTHON`
4. `G:\Python\python.exe`（本机便携默认）
5. PATH 中的 `python`
6. `py -3.13 / -3.12 / -3.11 / -3.10`

探测结果若缺少必需模块，会打印缺项和安装命令，而不是等到分析阶段才报错。

- 一键创建本地 venv：`powershell -NoProfile -ExecutionPolicy Bypass -File tools\bootstrap.ps1`；之后 `start_all.ps1` 会自动探测 `.venv\Scripts\python.exe`。
- 五个 Python 子项目均保留 `requirements.txt`（跨平台下限）与 `requirements-lock.txt`（参考环境直接依赖锁定；`edm-takens-web`、`trace-engine-web`、`trace-to-edm` 本轮补齐）。
- 单独检查：

```powershell
python tools\check_env.py
python tools\check_env.py --json
python tools\check_env.py --required numpy,pandas,jieba,dowhy,causallearn
```

## 4. Node 依赖

三个 Node 项目均已保留 `package-lock.json`，并已从 `.gitignore` 中放行：

- `trace-engine-web/package-lock.json`
- `trace-to-edm/package-lock.json`
- `edm-takens-web/frontend/package-lock.json`

安装：

```powershell
npm ci
```

若换机器且没有网络，可先在有网机器执行 `npm ci` 后整体拷贝 `node_modules`，但更推荐保留 lockfile 并用 `npm ci` 复现。

## 5. GraphRAG 依赖与补丁

- `GraphRAG-神纪图谱/requirements.txt` 锁定 `graphrag`/`lancedb` 等关键版本。
- `scripts/reapply-graphrag-patches.py` 负责重打 DeepSeek `response_format` 兼容补丁。
- 升级 `graphrag` 后必须重新运行补丁脚本；否则 drift/local 查询可能返回 HTTP 400。

```powershell
python scripts\reapply-graphrag-patches.py
python scripts\verify-env.py --no-services   # 数据/依赖检查；查询前可改用 --require-services
python scripts\verify-env.py --data-only --no-services   # CI：只验证 parquet/data_version
```

## 6. 浏览器回归（可选）

```powershell
python -m pip install -r Complement/tools/requirements-browser.txt
python -m playwright install chromium
python Complement/tools/browser_smoke.py              # 三页面加载
python Complement/tools/browser_smoke.py --full       # 真实 TRACE LIGHT + EDM 分析
```

`--full` 会真实触发分析，EDM 在 32 行示例数据上约需 3-5 分钟；脚本会检查 `column_mapping` 不再互换，并检查 TRACE 的合成 SEM 披露。

## 7. 已知环境陷阱

1. Windows PowerShell 5.1 的管道编码可能把中文变成 `?`；写文件优先用 `[IO.File]::WriteAllText` + UTF-8 no BOM。
2. 默认 `python` 不一定是本项目需要的解释器；以 `tools\check_env.py` 输出为准。
3. 模型目录大小写：代码与文档统一使用 `Models/`；Linux/macOS 大小写敏感，不能写成 `models/`。
4. GraphRAG 的 `settings.yaml` 默认走 `127.0.0.1:15721`（LLM 代理）与 `127.0.0.1:8081`（bge-m3）；启动查询前先确认两个端口。
