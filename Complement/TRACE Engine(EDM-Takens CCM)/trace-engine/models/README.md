# TRACE 引擎模型目录

本目录存放 Qwen 基础模型，用于 TRACE 引擎推理。

## 模型列表

| 目录 | 说明 |
| :--- | :--- |
| `Qwen2.5-1.5B-Instruct/` | Qwen2.5 1.5B 指令微调版 |
| `Qwen2.5-3B-Instruct/` | Qwen2.5 3B 指令微调版 |

## 模型来源

因文件超出 GitHub 大小限制，模型权重托管于**魔搭（ModelScope）**，请自行下载后放入对应目录。

**Qwen 官方魔搭仓库：**

| 模型 | 链接 |
| :--- | :--- |
| Qwen2.5-1.5B-Instruct | [🧩 魔搭下载](https://modelscope.cn/models/qwen/Qwen2.5-1.5B-Instruct) |
| Qwen2.5-3B-Instruct | [🧩 魔搭下载](https://modelscope.cn/models/qwen/Qwen2.5-3B-Instruct) |

```bash
# 使用魔搭 CLI 下载
pip install modelscope

modelscope download qwen/Qwen2.5-1.5B-Instruct --local_dir ./Qwen2.5-1.5B-Instruct
modelscope download qwen/Qwen2.5-3B-Instruct --local_dir ./Qwen2.5-3B-Instruct
```

> 注意：本目录仅保留模型配置文件，`.safetensors` 权重文件不随 GitHub 仓库上传。
