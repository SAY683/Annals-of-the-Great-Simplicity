# 故障排查与调试指南

## 1. 常见问题

### 服务启动失败

**症状**：`start_all.bat` 或单独启动脚本报错

**排查步骤**：
1. 检查 `cloudflared` 是否在 PATH 中
2. 检查 Python/Node.js 版本
3. 查看服务日志：
   - trace-engine-web: `work/server.log`、`work/server_err.log`
   - edm-takens-web: `mvp_out.log`、`mvp_err.log`
4. 检查端口是否被占用：`netstat -ano | findstr ":3000"`

### 隧道 URL 打不开

**症状**：`tunnel_url.txt` 中的 URL 无法访问

**原因**：URL 文件含 BOM 字符

**修复**：已修复为无 BOM 写入。如仍出现，手动删除 `tunnel_url.txt` 后重启隧道。

### EDM 任务返回 HTTP 500

**可能原因**：
1. `jobs.sqlite` 损坏或 0 字节 → 删除后重启后端自动重建
2. `results/` 目录不存在 → 已添加防御性创建
3. 结果含 NaN/Infinity → 已添加 `_sanitize_json` 清理

### EDM 任务返回 "error" 但无详细信息

**排查**：
```python
import urllib.request, json
req = urllib.request.Request('http://127.0.0.1:8000/api/analyze/jobs/{job_id}')
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
print(data.get('error'))
print(data.get('logs', [])[-20:])  # 最后 20 行日志
```

### HAVOK 退化警告

**症状**：`stability_tier: "N/A (degenerate HAVOK)"`

**原因**：样本量不足（N<30）或近常量信号

**解决**：收集更多数据点（>=30，理想 >=50）

### SUPER 模式 OOM

**症状**：显存不足，模型加载失败

**解决**：
1. 关闭其他占用显存的程序
2. 设置 `TRACE_MODEL_DTYPE=fp32` 强制 FP32
3. 缩短文本或减小 `window_size`/`max_segments`
4. 切换到 shehui-llama（27M，仅需 1.5GB）

## 2. 调试技巧

### 查看后端实时日志

```powershell
# edm-takens-web
Get-Content "edm-takens-web\mvp_err.log" -Wait -Tail 20

# trace-engine-web
Get-Content "trace-engine-web\work\server_err.log" -Wait -Tail 20
```

### 手动触发 EDM 任务

```python
import urllib.request, urllib.parse, json

data = urllib.parse.urlencode({
    'filename': 'your_data.csv',
    'target_col': 'your_target',
    'q': '3',
    'auto_fix': 'true',
}).encode('utf-8')

req = urllib.request.Request(
    'http://127.0.0.1:8000/api/analyze/jobs',
    data=data, method='POST'
)
req.add_header('Content-Type', 'application/x-www-form-urlencoded')
resp = urllib.request.urlopen(req, timeout=10)
result = json.loads(resp.read())
print(result)
```

### 副本同步检查

```powershell
cd edm-takens-web\backend
python sync_check.py
```

输出示例：
```
  [OK]   sovereign_havok.py
  [SKIP] _paths.py  (预期差异：副本定制)
  [DIFF] pipeline.py  核心库与副本不一致！

汇总: 18 一致 / 3 预期差异 / 1 不一致 / 0 副本缺失
```

### 清理残留进程

```powershell
# 停止所有 Python 后端
taskkill /F /IM python.exe

# 停止所有 Node 服务
taskkill /F /IM node.exe

# 停止所有 cloudflared
taskkill /F /IM cloudflared.exe
```

## 3. 已知限制

### pyEDM 在 Windows 上的问题
- `pyEDM.Multiview` 可能失败（multiprocessing spawn 模式）
- 使用 `numProcess=1` 绕过

### Python 3.13+ 问题
- `scipy` 多进程导入可能 MemoryError
- 设置 `OMP_NUM_THREADS=1`

### dowhy + pydot 兼容性
- `dowhy>=0.14` 搭配 `pydot>=3.0` 出现 `Graph.get_strict()` API 不兼容
- 使用 `pydot<3.0` 解决

### Shehui-LLaMA 因果边稀少
- 模型对 TRACE mask interventions 不敏感（训练/权重问题）
- 使用 `llama` 预设（`threshold=0.01`）可检出非零因果边
- 或切换到 Shenji-LLaMA

## 4. 日志级别

### trace-engine-web 日志格式

```
▶ STAGE[15:05:26] ▶ 触发 EDM: target=secular_entropy, 预测窗口=3步
✖ ERROR[15:05:28] ✗ EDM失败: API 调用失败: HTTP Error 500
▲ WARN[15:05:30] ⚠ 结果含 NaN 值，已清理
✓ DONE[15:06:00] ✓ 分析完成
```

### EDM 任务日志级别

| 图标 | 级别 | 说明 |
|------|------|------|
| ▶ | STAGE | 阶段开始 |
| ◉ | INFO | 一般信息 |
| ▲ | WARN | 警告（可继续） |
| ✖ | ERROR | 错误（任务失败） |
| ✓ | DONE | 完成 |

## 5. 性能调优

### 减少 EDM 分析时间
- 减少变量数量（`selected_vars`）
- 降低 `max_E`（嵌入维度上限）
- 使用 `auto_fix=true` 自动优化参数

### 减少 SUPER 模式时间
- 使用 shehui-llama（27M）而非 shenji-llama（469M）
- 减小 `window_size`（默认 128）
- 减小 `max_segments`（默认 3）
- 开启 `classical_mode=false`（减少 token 数）

### 并发限制
- EDM 分析：最多 1 个并发任务（`_ANALYSIS_LOCK`）
- SUPER 模式：单线程顺序执行（LLaMA Worker）
