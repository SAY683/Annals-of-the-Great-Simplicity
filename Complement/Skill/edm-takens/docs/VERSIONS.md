# 版本清单

## 当前版本

| 项目 | 版本 | 日期 | SHA256 | 测试状态 |
|------|------|------|--------|----------|
| edm-takens | Round 15 | 2026-07-15 | `b90c496e3b97022ae77cb1cf8f7d22b034944ba5a6d98ba399f8c142e5c2e7be` | 88/89 quick tests 通过 (ccm_causality.py 自测超时阈值已增至 600s) |
| edm-takens-web | Round 15 | 2026-07-15 | `ffb40ca43c78c2b275503bb70d57343358de079e8765d8852c62c077d0e6ae6a` | 14/15 verify_mvp.py 通过 (Vite 前端未启动，API 全通过) |

## 最近一次审计 (2026-07-15)

### 5 层审计结论
- **算法层**：核心算法 100% 一致（`_numpy_edm.py`、`sovereign_havok.py`、`ccm_causality.py` 一致）
- **桥接层**：`_edm_bridge.py` 双路径、`_paths.py` 环境变量支持、参数透传一致
- **模型层**：P0 bug 已修复（`final_interpretation.py` Phase 2 使用 `available_variables`）
- **信息层**：Web 端 25 个 API 端点完整，数据质量诊断/分析强度分级齐全
- **交付层**：`.gitignore` 已排除运行时产物，.skill 包已同步到便携目录

### 关键修复
- **P0**: `final_interpretation.py` 使用 `available_variables` 避免稀疏变量 KeyError
- **P1**: `pipeline.py` spike 输出添加列存在性防御检查
- **P2**: `.gitignore` 增加 `*.sqlite`、`jobs.sqlite`、`backend/results/` 规则

## 历史归档

旧版演进报告：`docs/edm-takens-skill-diff-report.md`（如存在）为历史文档，不再更新。
