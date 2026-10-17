# 10 · 模型位置、来源与校验

> 维护原则：`Models/` 与 `trace-engine/Models/` 的**位置不移动、不删除**。
> 两个目录分别承担“成品根共享资源”和“引擎内部副本”的角色，属于交叉依赖布局，不是普通缓存。

## 1. 两处模型目录的分工

| 位置 | 用途 | 主要引用方 |
|---|---|---|
| `TRACE Engine(EDM-Takens CCM)/Models/` | 成品根默认模型位置；Qwen L3 与 ModelScope 发布模型 | `trace-to-edm/config.py`、`layer3_sacred.py`、根 README |
| `TRACE Engine(EDM-Takens CCM)/trace-engine/Models/` | 引擎内部 SUPER 模式镜像 | `trace-engine-web/llama_worker.py`、`trace-engine/.../project_paths.py` |

`sync_product.py` 只会在源/目标大小不一致时复制，避免每次重写大文件。

> 大小写说明：Git 索引中保留了历史路径 `trace-engine/models/`（小写）；Windows 由于文件系统大小写不敏感会显示为 `Models/`。路径探测与校验代码现在同时匹配 `Models/` 和 `models/`，不要求用户手工改名。根级 `Models/` 是本地运行包资源，整个目录被 `.gitignore` 排除。

## 2. 模型清单与来源

### 2.1 自训练 LLaMA

| 模型 | 用途 | 大小 | ModelScope |
|---|---|---|---|
| `shenji-llama` | 神学/史诗古文 SUPER | 约 1.88 GB | [say101/TRACE-Engine-EDM-Takens-CCM-shenji-llama-470m](https://modelscope.cn/models/say101/TRACE-Engine-EDM-Takens-CCM-shenji-llama-470m) |
| `shehui-llama` | 默认 SUPER（27M） | 约 108 MB | [say101/TRACE-Engine-EDM-Takens-CCM-shehui-llama-27m](https://modelscope.cn/models/say101/TRACE-Engine-EDM-Takens-CCM-shehui-llama-27m) |
| `shehui-llama-v4-archive` | 旧版归档，不常用 | 约 1.88 GB | [say101/TRACE-Engine-EDM-Takens-CCM-shehui-llama-470m](https://modelscope.cn/models/say101/TRACE-Engine-EDM-Takens-CCM-shehui-llama-470m) |

### 2.2 Qwen 基础模型

| 模型 | 用途 | 大小 | ModelScope |
|---|---|---|---|
| `Qwen2.5-1.5B-Instruct` | `trace-to-edm` L3 神圣文本编码；便携布局探测信号 | 约 3.09 GB | [qwen/Qwen2.5-1.5B-Instruct](https://modelscope.cn/models/qwen/Qwen2.5-1.5B-Instruct) |
| `Qwen2.5-3B-Instruct` | 可选 L3 编码器 | 约 6.17 GB | [qwen/Qwen2.5-3B-Instruct](https://modelscope.cn/models/qwen/Qwen2.5-3B-Instruct) |

> 权重文件超过 GitHub 单文件限制，仓库只保留配置与 tokenizer 文件；权重需通过 ModelScope 下载后放入对应目录。

## 3. 下载与放置

```powershell
pip install modelscope

modelscope download say101/TRACE-Engine-EDM-Takens-CCM-shenji-llama-470m
modelscope download say101/TRACE-Engine-EDM-Takens-CCM-shehui-llama-27m
modelscope download qwen/Qwen2.5-1.5B-Instruct
# 可选
modelscope download qwen/Qwen2.5-3B-Instruct
```

下载后把 `.safetensors` 放到：

```text
Models/shenji-llama/model.safetensors
Models/shehui-llama/model.safetensors
Models/Qwen2.5-1.5B-Instruct/model.safetensors
Models/Qwen2.5-3B-Instruct/model-*.safetensors
```

引擎内部镜像：

```text
trace-engine/Models/shenji-llama/model.safetensors
trace-engine/Models/shehui-llama/model.safetensors
```

## 4. 校验

```powershell
python tools\verify_models.py
python tools\verify_models.py --sha256   # 计算 SHA256，耗时较长
python tools\verify_models.py --json
```

校验内容：存在性、文件大小、必需/可选标记、ModelScope 修复命令。

## 5. 许可与分发

- 代码遵循仓库根 `LICENSE`（MIT）。
- Qwen 模型目录自带许可证文件，分发时请保留。
- `shehui-llama`、`shenji-llama`、`shehui-llama-v4-archive` 是作者自训练模型；作者已确认采用与本仓库整体一致的 **MIT License**。完整文本见 `MODEL_LICENSE.md` 与 `trace-engine/models/LICENSE`。
- ModelScope 当前模型页的 `License/LicenseName/LicenseLink` 字段尚未同步为 MIT；第三方再分发时应以仓库中的 `MODEL_LICENSE.md` 为准，并建议作者在 ModelScope 模型卡中同步许可证。
- GraphRAG 的源文本与图谱属于《神纪》作品体系，见 `GraphRAG-神纪图谱/docs/06-责任与合规.md`。