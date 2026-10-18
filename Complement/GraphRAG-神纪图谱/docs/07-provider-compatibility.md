# 07 · Provider 能力兼容层

## 1. 为什么需要这一层

GraphRAG 的若干索引与搜索步骤会通过 `response_format` 或
`response_format_json_object` 要求模型返回严格 JSON。OpenAI 官方模型通常支持这种
JSON response mode，但 DeepSeek、Ollama 以及部分本地代理可能拒绝相关参数，表现为
HTTP 400/404/422，或在正文外附带代码围栏、说明文字和尾逗号。

早期做法是直接修改 `site-packages/graphrag`。该做法会在 `pip` 升级时失效，也会让不同
机器上的行为难以复现。本项目现在改为**运行时能力兼容层**：不修改第三方包，在 GraphRAG
导入 completion 模块之前安装包装器。

## 2. 入口与调用链

统一入口：

```powershell
python scripts\graphrag_compat_cli.py --help
python scripts\graphrag_compat_cli.py query --root project --method global "什么是爱？"
python scripts\graphrag_compat_cli.py index --root project
```

调用链：

```text
graphrag_compat_cli.py
  -> graphrag_compat.install()
  -> 包装 graphrag_llm.completion.create_completion
  -> 导入并运行 GraphRAG CLI
```

`mcp/graphrag_mcp.py`、`scripts/rebuild-index.ps1` 与 `scripts/selfcheck-query.ps1` 都已
切换到该入口。`scripts/reapply-graphrag-patches.py` 仅保留给旧环境排障，不属于正常安装
或升级流程。

## 3. 能力探测与回退

默认 `GRAPHRAG_JSON_MODE=auto`：

- 模型/provider/API base 中含 `deepseek`、`ollama`、`127.0.0.1:15721` 或
  `localhost:15721` 时，默认不使用 JSON response mode。
- 其它 provider 先按“支持”处理；若调用仍返回 400/404/422，或错误明确提到
  `response_format` / `json_object` / `unsupported parameter`，自动去掉 JSON mode
  重试一次。
- 可用 `GRAPHRAG_JSON_MODE=on` 强制启用，或 `off` 强制关闭。

覆盖范围：

- `completion`
- `completion_async`
- `completion_batch`
- `completion_thread_pool`

因此索引、Local/Global/Drift/Basic 查询和社区报告生成不会各自走不同逻辑。

## 4. JSON 容错

统一解析器会处理：

- Markdown 代码围栏；
- JSON 前后的解释性文字；
- 尾逗号；
- `json_repair` 可修复的常见模型输出错误。

社区报告的 `model_validate_json` 也在内存中加了同等的预处理，避免模型正文格式差异
直接中断索引构建。

## 5. 验证

```powershell
python -m pytest graphrag_compat\tests -q
python scripts\graphrag_compat_cli.py --help
python scripts\verify-env.py --data-only --no-services
```

CI 已包含兼容层单测。真实查询仍需要 `settings.yaml` 中配置的 LLM 与 embedding 服务
（默认 `127.0.0.1:15721` 和 `127.0.0.1:8081`）在线；静态测试通过不等于外部模型服务
已经可用。

## 6. 设计边界

- 这是对第三方库调用边界的兼容包装，不是对 GraphRAG 上游实现的替代。
- 如果上游未来原生提供 provider capability profile，可删除本层并改用上游配置。
- 发生变化时应优先扩展 `CapabilityProfile` 与单测，而不是重新修改 `site-packages`。