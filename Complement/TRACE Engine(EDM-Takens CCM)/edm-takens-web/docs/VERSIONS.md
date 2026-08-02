# 版本清单

## 当前版本

| 项目 | 版本 | 日期 | SHA256 | 测试状态 |
|------|------|------|--------|----------|
| edm-takens-web | Round 15（对应 package.json 0.1.0） | 2026-07-15 | `ffb40ca43c78c2b275503bb70d57343358de079e8765d8852c62c077d0e6ae6a` | 修复前 12/15 verify_mvp.py 通过（3 项失败）；job_store.recover() 修复后 15/15 全通过 |
| 配套原生 skill | Round 15 | 2026-07-15 | `b90c496e3b97022ae77cb1cf8f7d22b034944ba5a6d98ba399f8c142e5c2e7be` | 88/89 quick tests 通过 |

## 最近一次审计 (2026-07-15)

### 5 层审计结论
- **算法层**：与原生端核心算法文件一致
- **桥接层**：`_edm_bridge.py` Windows 死锁修复、`_paths.py` 环境变量支持一致
- **模型层**：`final_interpretation.py`、`enhanced_cross_validate.py` 与原生端同步
- **信息层**：25 个 API 端点覆盖上传/分析/下载/归档/质量诊断/批量导出
- **交付层**：前端 `main.js` 33 个函数完整，.gitignore 排除运行时产物

### 已知待启动项
- `verify_mvp.py` 前端检查项需要手动启动 Vite 开发服务器 (`cd frontend && npm run dev`)
- 其余 14 项 API/算法验证：修复前 3 项失败（崩溃任务恢复缺失等 P0 问题）；`backend/job_store.py` 新增 `recover()` 后 14 项全部通过
