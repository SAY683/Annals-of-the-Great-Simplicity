# Round 21 — 技术债务清单 + 破坏性测试设计

> 创建: 2026-07-27
> 范围: 5 项目全量化技术债务 + 7 项破坏性测试
> 视角: PM + 算法工程师 + 安全审计
> 关联: ROUND21_ACTION_PLAN.md P1-C

---

## 0. 技术债务全量化清单

### 0.1 P0 级债务（阻断性，需立即处理）

| ID | 债务 | 来源 | 状态 | 修复复杂度 |
|----|------|------|------|-----------|
| D-P0-1 | Pearl 三步反事实缺失拓扑排序 | ROUND21_ALGORITHM_AUDIT | 待修 | 50 行 (拓扑排序+环检测) |
| D-P0-2 | enhanced_cross_validate "CV"违反独立性 | ROUND21_ALGORITHM_AUDIT | 待修 | 100 行 (block bootstrap) |
| D-P0-3 | SimulationEstimand 硬编码 identifiable=True | ROUND21_ALGORITHM_AUDIT | 待修 | 10 行 (synthetic 标记) |
| D-P0-4 | edm-takens-web 全端点零鉴权 | ROUND21_API_AUDIT | 待修 | 30 行 (Depends 链) |

### 0.2 P1 级债务（重要，影响可信度）

| ID | 债务 | 来源 | 状态 | 修复复杂度 |
|----|------|------|------|-----------|
| D-P1-1 | trace-engine-web 鉴权 fail-open | ROUND21_API_AUDIT P1-1 | 待修 | 15 行 |
| D-P1-2 | trace-engine-web 错误响应格式碎片化 (4种) | ROUND21_API_AUDIT P1-2 | 待修 | 全路由统一 |
| D-P1-3 | trace-engine-web 管理员操作无审计日志 | ROUND21_API_AUDIT P1-3 | 待修 | 10 行/路由 |
| D-P1-4 | trace-to-edm 22/32 端点错误回 e.message | ROUND21_API_AUDIT P1-4 | 待修 | 全路由统一 |
| D-P1-5 | trace-to-edm API Key 中间件 try-catch 降级 | ROUND21_API_AUDIT P1-5 | 待修 | 5 行 |
| D-P1-6 | edm-takens-web 全仓零日志 | ROUND21_API_AUDIT P1-6 | 待修 | logging 配置 |
| D-P1-7 | edm-takens-web GET /api/analyze/stream 违反 REST | ROUND21_API_AUDIT P1-7 | 待修 | 拆分 POST+GET |
| D-P1-8 | edm-takens-web restore 无 zip bomb 防护 | ROUND21_API_AUDIT P1-8 | 待修 | 10 行 |
| D-P1-9 | trace-to-edm 单文件 1594 行无 Router | ROUND21_API_AUDIT P1-9 | 待修 | 拆分 8 Router |
| D-P1-10 | _numpy_edm S-Map NaN 传播 | ROUND21_ALGORITHM_AUDIT P1-1 | 待修 | 15 行 |
| D-P1-11 | _numpy_edm S-Map 秩亏静默 | ROUND21_ALGORITHM_AUDIT P1-2 | 待修 | 10 行 |
| D-P1-12 | ccm_causality Spearman 独立性违反 | ROUND21_ALGORITHM_AUDIT P1-6 | 待修 | 20 行 (effective N) |
| D-P1-13 | final_interpretation R²≥0.5 偏松 | ROUND21_ALGORITHM_AUDIT P1-8 | 待修 | 三级分级 |
| D-P1-14 | counterfactual_bridge condition_number 静默过滤 | ROUND21_ALGORITHM_AUDIT P1-10 | 待修 | 5 行 |
| D-P1-15 | trace-to-edm 无不确定性披露 | ROUND21_EXPORT_AUDIT | 待修 | 30 行 |
| D-P1-16 | trace-to-edm/edm-takens-web 缺 SEM 标记 | ROUND21_EXPORT_AUDIT | 待修 | 10 行 |
| D-P1-17 | 三份 Lyapunov 实现不一致 | ROUND21_ALGORITHM_AUDIT | 待修 | 统一委托 |

### 0.3 P2 级债务（改进建议）

| ID | 债务 | 来源 | 状态 |
|----|------|------|------|
| D-P2-1 | trace-to-edm 端点数注释过期 (31 vs 32) | ROUND21_INTEGRITY_MATRIX | 待修 |
| D-P2-2 | edm-takens-web intensity 无 enum 校验 | ROUND21_API_AUDIT P2 | 待修 |
| D-P2-3 | sovereign_havok K_d_ legacy 误导 | ROUND21_ALGORITHM_AUDIT | 待修 |
| D-P2-4 | sovereign_havok 注释-代码不一致 (r-1 vs r) | ROUND21_ALGORITHM_AUDIT P1-16 | 待修 |
| D-P2-5 | pearl_counterfactual 文档公式过时 (CDE vs Y(t')) | ROUND21_ALGORITHM_AUDIT P1-15 | 待修 |
| D-P2-6 | _numpy_edm Multiview 死代码 | ROUND21_ALGORITHM_AUDIT | 待修 |
| D-P2-7 | edm_adaptive_pipeline docstring 承诺 ccm_results 未实现 | ROUND21_ALGORITHM_AUDIT | 待修 |
| D-P2-8 | trace-engine-web top_edges 缺 p_value 列 | ROUND21_EXPORT_AUDIT | 待修 |

**债务统计**: P0=4, P1=17, P2=8, 总计 29 项

---

## 1. 破坏性测试设计

### 1.1 测试矩阵

| # | 测试 | 目的 | 输入 | 预期响应 | 实际验证 |
|---|------|------|------|---------|---------|
| DT-1 | 输入空文本 | 校验链路 | `text=""` | 400 + EMPTY_TEXT | 待执行 |
| DT-2 | 输入超长文本 (10MB) | 限流 | 10MB 文本 | 413 / 400 | 待执行 |
| DT-3 | 输入非 UUID | 路径遍历 | `id="../../etc/passwd"` | 400 + INVALID_ID | 待执行 |
| DT-4 | 输入污染数据 (NaN/Inf) | 数据质量 | CSV 含 NaN | 422 + DATA_QUALITY | 待执行 |
| DT-5 | 输入半全数据 (50% 缺失) | 适配 | CSV 50% NaN | 警告 + 降级 | 待执行 |
| DT-6 | 端口冲突重启 | 进程管理 | 端口占用时启动 | 自动清理 | 待执行 |
| DT-7 | 跨项目跳转 (隧道) | URL 重写 | trycloudflare URL | 域名识别 | 待执行 |

### 1.2 测试脚本框架

```python
# 破坏性测试框架（伪代码）
import requests
import pytest

@pytest.mark.parametrize("endpoint,method,payload,expected_status,expected_code", [
    # DT-1: 空文本
    ("http://127.0.0.1:3000/api/jobs", "POST", {"text": ""}, 400, "EMPTY_TEXT"),
    # DT-2: 超长文本
    ("http://127.0.0.1:3000/api/jobs", "POST", {"text": "x" * 10_000_000}, 413, None),
    # DT-3: 路径遍历
    ("http://127.0.0.1:3000/api/retry/../../etc/passwd", "POST", {}, 400, "INVALID_ID"),
    # DT-4: 污染数据
    ("http://127.0.0.1:8000/api/analyze", "POST", {"filename": "nan_inf.csv"}, 422, "DATA_QUALITY"),
    # DT-5: 半全数据
    ("http://127.0.0.1:8000/api/analyze", "POST", {"filename": "half_missing.csv"}, 200, None),
])
def test_destructive(endpoint, method, payload, expected_status, expected_code):
    resp = requests.request(method, endpoint, json=payload, timeout=30)
    assert resp.status_code == expected_status
    if expected_code:
        assert resp.json().get("code") == expected_code
```

### 1.3 数据污染测试 CSV 生成

```python
# nan_inf.csv 生成
import pandas as pd
import numpy as np
df = pd.DataFrame({
    'time': range(50),
    'x': [np.nan if i % 5 == 0 else np.random.randn() for i in range(50)],
    'y': [np.inf if i % 7 == 0 else np.random.randn() for i in range(50)],
})
df.to_csv('nan_inf.csv', index=False)

# half_missing.csv 生成
df = pd.DataFrame({
    'time': range(100),
    'x': [np.nan if i % 2 == 0 else np.random.randn() for i in range(100)],
    'y': np.random.randn(100),
})
df.to_csv('half_missing.csv', index=False)
```

---

## 2. 端口/进程管理协议 (回应需求 #8)

### 2.1 端口分配

| 端口 | 项目 | 启动脚本 | 用途 |
|------|------|---------|------|
| 3000 | trace-engine-web | start.bat / start.ps1 | 因果推断 Web |
| 3100 | trace-to-edm | start.bat / start.ps1 | 轨迹桥接 Web |
| 8000 | edm-takens-web | start_mvp.bat / start_mvp.py | EDM-Takens Web |
| 8765 | cloudflared | tunnel.ps1 / 启动隧道.bat | Cloudflare Tunnel |
| 3030 | verify_portable | verify_portable.py | 便携验证临时 |

### 2.2 启动前检查协议

```powershell
# 启动前检查端口占用
function Test-PortAvailable {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $pid = $conn.OwningProcess
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        Write-Warning "端口 $Port 被 PID $pid ($($proc.ProcessName)) 占用"
        return $false
    }
    return $true
}

# 启动前清理
function Stop-PortProcesses {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $pid = $conn.OwningProcess
            # 匹配 *server.js* 并排除 vite 开发服务器
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($proc.ProcessName -eq 'node') {
                $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$pid").CommandLine
                if ($cmdline -match 'server\.js' -and $cmdline -notmatch 'vite') {
                    Stop-Process -Id $pid -Force
                    Write-Host "已清理 PID $pid (端口 $port)"
                    Start-Sleep -Seconds 2
                }
            }
        }
    }
}
```

### 2.3 冲突预案

| 场景 | 现象 | 处置 |
|------|------|------|
| 端口被 node server.js 占用 | EADDRINUSE | Stop-Process + 重试 |
| 端口被 vite 占用 | EADDRINUSE | **禁止杀** — 提示用户手动关闭 |
| 端口被 python 占用 | EADDRINUSE | Stop-Process + 重试 |
| 端口被系统服务占用 | EADDRINUSE | 换端口 (3000→3001→...) |

**禁止操作**:
- `taskkill /F /IM node.exe` — 会杀掉 vite 开发服务器
- `taskkill /F /IM python.exe` — 会杀掉所有 Python 进程

---

## 3. 4 角色互审

### PM 视角
- 29 项技术债务中 P0=4, P1=17，需排期处理
- 破坏性测试 7 项是用户可感知的健壮性保障
- 端口管理协议避免"频繁多重开启导致核查冲突"

### 算法工程师视角
- Pearl 拓扑排序是最高优先级算法债务
- _numpy_edm S-Map 数值稳定性三连缺需系统性修复
- 三份 Lyapunov 实现应统一委托

### 数学家视角
- condition_number 静默过滤是"症状消除"而非"病因治疗"
- Spearman 独立性违反需 effective sample size 修正

### 统计家视角
- 破坏性测试 DT-4 (NaN/Inf) 和 DT-5 (50% 缺失) 是数据质量保障
- trace-to-edm 无不确定性披露是最大统计严谨性缺口

---

## 4. 验收清单

- [x] 技术债务全量化清单 (29 项)
- [x] 破坏性测试设计 (7 项)
- [x] 端口/进程管理协议
- [x] 4 角色互审
- [ ] 破坏性测试执行（需服务运行）
