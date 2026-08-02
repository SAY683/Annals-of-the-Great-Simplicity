# 故障排除指南

## 常见问题

### 1. 后端启动失败

**症状**：`python run_backend.py` 报错

**可能原因**：
- 端口 8000 被占用
- 依赖未安装
- Python 版本不兼容

**解决方案**：
```bash
# 检查端口占用
netstat -ano | findstr :8000

# 安装依赖
pip install -r requirements.txt

# 检查 Python 版本（需要 3.10+）
python --version
```

### 2. 前端无法访问

**症状**：浏览器打开 `http://localhost:5173` 显示空白

**可能原因**：
- 前端未构建
- Vite 开发服务器未启动

**解决方案**：
```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

### 3. 分析任务卡住

**症状**：提交分析后，进度一直停在某个阶段

**可能原因**：
- 数据量过大
- 参数设置不当
- 后端异常

**解决方案**：
1. 检查后端日志（后端默认不写日志文件，输出到启动时的控制台）：
```bash
# 查看后端控制台输出；启动时可加 -u 禁用输出缓冲
python -u run_backend.py
```

2. 降低分析强度：
   - 使用 `light` 或 `medium` 配置
   - 减少变量数量

3. 检查数据质量：
   - 确保没有全空列
   - 确保时间序列长度 > 30

### 4. CCM 分析失败

**症状**：CCM 阶段报错或返回全 NA

**可能原因**：
- 样本量过小（N < 30）
- 变量过于稀疏（二值序列）
- 变量间无因果关系

**解决方案**：
1. 增加样本量
2. 检查变量分布：
```python
import pandas as pd
df = pd.read_csv('your_data.csv')
print(df.describe())
```

3. 使用 `data_quality.py` 诊断：
```bash
curl -X GET "http://localhost:8000/api/datasets/your_file.csv/quality"
```

### 5. Windows 多进程死锁

**症状**：分析任务在 Windows 上卡死

**可能原因**：
- pyEDM 2.5+ 多进程实现与 Windows spawn 模式不兼容

**解决方案**：
已在 `_edm_bridge.py` 中修复：
- `EmbedDimension` 和 `CCM` 强制使用 `numProcess=1`
- `CCM` 在 Windows 上使用 `legacy='ccm_24'` 模式

无需手动干预。

### 6. 数据路径错误

**症状**：找不到数据文件或无法访问上传的数据

**可能原因**：
- 数据路径配置错误
- 环境变量未设置

**解决方案**：
1. 检查 `_paths.py`：
```python
from _paths import SKILL_DATA, data_path
print(SKILL_DATA)
print(data_path('test.csv'))
```

2. 设置环境变量：
```bash
# Windows
set EDMTAKENS_DATA_DIR=C:\path\to\your\data

# Linux/Mac
export EDMTAKENS_DATA_DIR=/path/to/your/data
```

### 7. 内存不足

**症状**：分析过程中内存溢出

**可能原因**：
- 数据量过大
- 嵌入维度过高
- 多进程内存复制

**解决方案**：
1. 减少变量数量
2. 降低嵌入维度：
```python
# 在 analysis_profiles.py 中调整（与默认推荐值一致）
'light': {'max_e': 6},
'medium': {'max_e': 8},
'heavy': {'max_e': min(12, max(8, n // 5))}
```

3. 使用 `numProcess=1`（已默认启用）

### 8. 结果图片无法显示

**症状**：分析完成后，图片无法加载

**可能原因**：
- 结果目录权限问题
- 图片路径错误

**解决方案**：
1. 检查 `results/` 目录权限
2. 检查任务 ID 对应的子目录：
```bash
ls results/{task_id}/
```

3. 重新生成图片：
```bash
curl -X GET "http://localhost:8000/api/results/{task_id}/dynamics_interpretation.png"
```

## 调试技巧

### 1. 启用详细日志

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 2. 检查算法中间结果

```python
from edmtakens.pipeline import run_full_analysis
result = run_full_analysis(config, auto_fix=False)
print(result.keys())
```

### 3. 验证数据质量

```python
from edmtakens.data_quality import evaluate_dataframe
report = evaluate_dataframe(df, target_col='target', selected_vars=['var1', 'var2'])
print(report)
```

### 4. 测试单个算法

```python
from edmtakens._edm_bridge import EmbedDimension
import pandas as pd

df = pd.read_csv('test.csv')
result = EmbedDimension(data=df, columns='var1', target='var1', maxE=8)
print(result)
```

## 联系支持

如果以上方案无法解决问题，请提供：
1. 完整的错误日志
2. 数据文件的前几行（脱敏）
3. 操作系统和 Python 版本
4. 复现步骤
