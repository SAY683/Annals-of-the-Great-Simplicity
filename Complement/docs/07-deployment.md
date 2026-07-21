# 部署、隧道与便携目录维护

## 1. 便携目录结构

```
Complement/
├── start_all.bat / start_all.ps1     # 统一启动脚本
├── Skill/
│   ├── edm-takens/                    # 项目 1: 核心库
│   ├── edm-takens-web/                # 项目 2: Web 服务
│   └── README.md
├── TRACE Engine(EDM-Takens CCM)/
│   ├── trace-engine/                  # 项目 3: 引擎
│   ├── trace-engine-web/              # 项目 4: Web 服务
│   ├── trace-to-edm/                  # 项目 5: 桥接层
│   ├── Models/                        # LLaMA 模型
│   ├── verify_portable.py             # 便携验证
│   └── sync_product.py                # 同步脚本
└── docs/                              # 本文档集
```

## 2. 同步机制

### 从源目录同步到便携目录

```powershell
# 同步 edm-takens + edm-takens-web
cd F:\攻略\研发测试\.skills
python sync_all_portable.py

# 同步 trace-engine + trace-engine-web + trace-to-edm
cd F:\攻略\研发测试\.skills\trace-engine-web
python sync_product.py
```

### 同步规则

- **白名单文件**：`sync_all_portable.py` 使用黑名单排除运行时产物
- **排除项**：`__pycache__/`、`outputs/`、`tunnel_logs/`、`*.log`、`jobs.sqlite`、`tunnel_url.txt`
- **同步方式**：覆盖而非先删后写（保留 `verify_portable.py` 和 `README.md`）
- **副本检查**：`edm-takens-web/backend/sync_check.py` 验证 `edmtakens/` 与 `edm-takens/src/` 一致性

### 便携目录验证

```powershell
cd "Complement"
python "TRACE Engine(EDM-Takens CCM)\verify_portable.py"
```

检查项：
- 目录结构完整性
- 无运行时产物污染
- 引擎模块导入与健康状态
- Web 服务健康检查
- API 配置契约（`/api/config` 含 SUPER mode、`bridgeParamSchema` 含 `max_segments`）

## 3. Cloudflare 隧道

### 隧道脚本结构

每个 Web 服务都有独立的隧道脚本：

```
trace-engine-web/
├── 启动隧道.bat       # GBK 编码，cmd 入口
└── tunnel.ps1         # UTF-8 编码，PowerShell 主体

trace-to-edm/
── 启动隧道.bat
└── tunnel.ps1

edm-takens-web/
├── 启动隧道.bat
└── tunnel.ps1
```

### 隧道脚本要点

- **编码**：`.bat` 使用 GBK + CRLF；`.ps1` 使用 UTF-8 + BOM
- **路径**：全部使用相对路径（`cd /d "%~dp0"` 后引用 `"tunnel.ps1"`）
- **日志**：时间戳命名，归档到 `tunnel_logs/` 子目录，每次启动只保留最新
- **URL 写入**：`[System.IO.File]::WriteAllText` + `UTF8Encoding $false`（无 BOM）
- **进程清理**：仅清理自身 cloudflared 进程，不误杀其他隧道
- **预检查**：检测 `cloudflared` 是否安装，缺失时提供安装链接
- **错误处理**：`.ps1` 包含 `catch` 块防止窗口关闭

### 统一启动

```powershell
# start_all.bat 集中启动三个隧道
.\start_all.bat
```

`start_all.ps1` 依次启动三个服务 + 隧道，每个在独立窗口中运行。

## 4. 端口管理

| 服务 | 默认端口 | 回退范围 | 检测方式 |
|------|----------|----------|----------|
| trace-engine-web | 3000 | 3000-3020 | PowerShell `Get-NetTCPConnection` |
| trace-to-edm | 3100 | 3100-3120 | 同上 |
| edm-takens-web | 8000 | 固定 | — |

## 5. 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TRACE_WORK_DIR` | TRACE 工作/输出目录 | 脚本目录 |
| `TRACE_ENGINE_SKILL_DIR` | 引擎 Skill 路径 | 自动探测 |
| `TRACE_PYTHON_CMD` | Python 命令 | `python` |
| `PORT` | Web 服务端口 | 各项目默认值 |
| `TRACE_STAGE_TIMEOUT_MS` | SUPER 模式看门狗超时 | 900000 |
| `EDMTAKENS_DATA_DIR` | EDM 数据目录 | 自动探测 |
| `JOBS_DB` | EDM 任务数据库路径 | `jobs.sqlite` |

## 6. 维护清单

### 日常维护
- [ ] 运行 `verify_portable.py` 验证便携目录完整性
- [ ] 检查 `sync_check.py` 确认副本一致性
- [ ] 清理 `tunnel_logs/` 旧日志（脚本自动处理）

### 代码修改后
- [ ] 修改 `edm-takens/src/` 后同步到 `edm-takens-web/backend/edmtakens/`
- [ ] 运行 `sync_check.py` 验证
- [ ] 运行 `sync_all_portable.py` 同步到便携目录
- [ ] 运行 `verify_portable.py` 确认

### 模型更新
- [ ] 新模型放入 `Models/` 目录（不带版本后缀）
- [ ] 同步到 `trace-engine/models/`
- [ ] 更新 `presets.yaml` 参数（如需要）
