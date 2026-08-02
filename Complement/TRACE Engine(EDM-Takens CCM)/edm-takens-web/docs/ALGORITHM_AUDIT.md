# 算法审计报告

## 审计概述

**审计日期**：2026-07-15  
**审计范围**：edm-takens-web 核心算法层  
**审计目标**：确保与 edm-takens 原生版本算法一致性

## 审计层级

### 1. 算法层 ✅ 通过

**核心文件完整性**：
- ✅ `_edm_bridge.py`：包含 EmbedDimension, Simplex, SMapPredictNonlinear, CCM
- ✅ `_numpy_edm.py`：numpy 回退实现
- ✅ `ccm_causality.py`：CCM 因果关系检测
- ✅ `sovereign_havok.py`：HAVOK 动力学分解
- ✅ `enhanced_cross_validate.py`：增强交叉验证
- ✅ `final_interpretation.py`：最终解释层

**关键函数检查**：
- ✅ `EmbedDimension`：嵌入维度优化
- ✅ `Simplex`：单纯形预测
- ✅ `SMapPredictNonlinear`：S-Map 非线性预测
- ✅ `CCM`：收敛交叉映射

### 2. 桥接层 ✅ 通过

**_edm_bridge.py 一致性**：
- ✅ Windows 多进程死锁修复：`numProcess=1`
- ✅ pyEDM 可用性检查：`EDM_AVAILABLE` 标志
- ✅ numpy 回退机制：`_numpy_edm.py`

**环境变量支持**：
- ✅ `EDMTAKENS_DATA_DIR`：支持环境变量覆盖数据路径
- ✅ 相对路径解析：基于 `__file__` 定位

### 3. 模型层 ✅ 通过

**核心模型文件**：
- ✅ `sovereign_havok.py`：包含 `SovereignHAVOK`, `classify_havok_stability`
- ✅ `ccm_causality.py`：包含 `ccm_causality_test`, `verify_ccm_direction`
- ✅ `enhanced_cross_validate.py`：包含 `run_enhanced_validation`, `estimate_lyapunov_exponent`

**测试入口**：
- ✅ `verify_mvp.py`：端到端验证脚本

### 4. 信息层 ✅ 通过

**参数传递**：
- ✅ `pipeline.py`：支持 `variables` 和 `target_col` 参数
- ✅ `enhanced_cross_validate.py`：函数签名支持自定义变量

**异常处理**：
- ✅ `enhanced_cross_validate.py`：每个变量分析都有 try/except 保护
- ✅ `final_interpretation.py`：变量过滤支持 `available_variables` 和 `skipped_variables`

### 5. 交付层 ✅ 通过

**打包产物**：
- ✅ `.skill` 文件：276.2 KB（40个文件）
- ✅ `.gitignore`：排除 `results/`, `archive/`, `__pycache__/`

**文档完整性**：
- ✅ `README.md`：项目说明
- ✅ `docs/TECHNICAL.md`：技术文档
- ✅ `docs/CHANGELOG.md`：变更日志
- ✅ `docs/ALGORITHM_AUDIT.md`：算法审计报告

## 算法一致性验证

### 与 edm-takens 原生版本对比

| 文件 | 状态 | 差异说明 |
|------|------|----------|
| `_edm_bridge.py` | ✅ 高度一致 | Web 版本仅删除未使用的 `import os`（`numProcess=1` 原版已有，非 Web 版新增） |
| `_numpy_edm.py` | ✅ 一致 | 无差异 |
| `ccm_causality.py` | ✅ 高度一致 | Web 版本回退了 `_SELFTEST_LIB_SIZES` 速度调优 |
| `sovereign_havok.py` | ✅ 一致 | 无差异 |
| `enhanced_cross_validate.py` | ✅ 高度一致 | Web 版本将硬编码列名泛化为 `target_col` / `variables` 参数 |
| `final_interpretation.py` | ✅ 高度一致 | Web 版本将硬编码列名泛化为 `target_col` / `variables`（大规模重构，非仅保留 `lib_sizes`） |
| `pipeline.py` | ✅ 一致 | 字节级一致（`variables` / `target_col` 参数原版已支持，非 Web 版新增） |
| `_paths.py` | ✅ 高度一致 | 默认数据路径指向 sibling skill，支持 `EDMTAKENS_DATA_DIR` 环境变量 |
| `edm_auditor.py` | ✅ 高度一致 | 新增 1 行 docstring 注释 |

### Web 版本独有功能

| 文件 | 功能 | 必要性 |
|------|------|--------|
| `data_quality.py` | 数据质量诊断 | ✅ 必要：处理用户上传数据 |
| `analysis_profiles.py` | 分析强度分级 | ✅ 必要：自动推荐参数 |

## 结论

**总体状态**：✅ 通过

**关键发现**：
1. 核心算法与 edm-takens 原生版本高度一致，6 个文件有适应性修改（详见上表）
2. Web 版本在保持算法高度一致性的基础上，添加了必要的 Web 适配功能
3. 异常处理和参数传递机制完善
4. 打包产物和文档完整

**建议**：
- 无需进一步修改，可交付使用

---

## §2.3 跨项目同步修复记录（ROUND28 科研披露落地）

**同步日期**：2026-07-31
**同步范围**： edm-takens 核心库 (`Skill/edm-takens/src/`) → edm-takens-web 副本 (`backend/edmtakens/`)
**触发原因**： ROUND26-27 科研严谨性审查发现 Web 副本失同步 10 个文件 + 1 个缺失文件，导致 4 个科研披露字段端到端缺失。

### 同步失同步文件清单（11 项）

| 文件 | 失同步根因 | 同步后状态 |
|------|-----------|-----------|
| `_numeric_constants.py` | Web 副本完全缺失（核心库 ROUND27 新建） | ✅ 新建副本 |
| `_numpy_edm.py` | S1-3 修复（effective_lib_sizes + out_of_sample_used）未同步 | ✅ SHA256 一致 |
| `ccm_causality.py` | S1-1/S1-2 修复（IAAFT silent failure + is_strict_confirmatory）未同步 | ✅ SHA256 一致 |
| `data_quality.py` | EPS_VARIANCE 常量替换未同步 | ✅ SHA256 一致 |
| `edm_auditor.py` | EPS_DISTANCE/EPS_PROB 常量替换未同步 | ✅ SHA256 一致 |
| `edm_tau_optimization.py` | P1-4 修复（KSG 估计器 + bins 自适应）未同步 | ✅ SHA256 一致 |
| `enhanced_cross_validate.py` | P0-1 修复（Lyapunov log(0) 防护）未同步 | ✅ SHA256 一致 |
| `final_interpretation.py` | EPS_LYAPUNOV 常量替换未同步 | ✅ SHA256 一致 |
| `pipeline.py` | S2-3 修复（reproducibility_seed + 独立 Generator）未同步 | ✅ SHA256 一致 |
| `sensitivity_config.py` | EPS_DISTANCE/EPS_VARIANCE 常量替换未同步 | ✅ SHA256 一致 |
| `sovereign_havok.py` | S2-1/S2-2 修复（Gavish-Donoho 公式 + lambda(beta) 表值）未同步 | ✅ SHA256 一致 |

### 科研披露字段端到端落地（S1-4 修复）

4 个科研披露字段已从底层算法 → 中间层 summary_builder → 前端 main.js → 前端 style.css 全链路打通：

| 字段 | 来源 | 透传层 | 渲染层 | 视觉区分 |
|------|------|--------|--------|----------|
| `is_strict_confirmatory` | ccm_causality.py:761-763 | summary_builder.py:156 | main.js:776-779 | `.ccm-badge-confirmatory` (蓝) / `.ccm-badge-exploratory` (琥珀) |
| `methodology_disclaimer` | ccm_causality.py:744-758 | summary_builder.py:157 | main.js:789-795 | `.ccm-disclaimer` (琥珀左边框突出) |
| `effective_lib_sizes` | _numpy_edm.py:663,701 | summary_builder.py:141 | main.js:800-802,837 (sparkline tooltip) | `code.sparkline` (绿底) |
| `out_of_sample_used` | _numpy_edm.py:664,702 | summary_builder.py:142 | main.js:818-823 (OOS/IN-SAMPLE 徽章) | `.ccm-oos-yes` (绿) / `.ccm-oos-no` (琥珀) |

### 验证

- `sync_check.py`：20 一致 / 2 预期差异 / 0 不一致 / 0 副本缺失 ✅
- 4 个科研披露字段在前端可见，科研用户可据此判断结论可信度 ✅
- 配色遵循科研论文惯例：蓝色=确认性，琥珀色=探索性/警告 ✅

### 与核心库 ALGORITHM_AUDIT.md 同步状态

核心库 `Skill/edm-takens/docs/ALGORITHM_AUDIT.md` §2.3 已记录 P0-1/P1-2/P1-4/S2-1/S2-2/S2-3/S1-1/S1-2/S1-3 共 9 项跨项目同步修复。本节补充 S1-4（科研披露字段端到端落地）作为 ROUND28 的最终闭环。

### sync_check.py 扩展

`sync_check.py` 现校验 22 个 `.py` 文件（含 `_numeric_constants.py`），但仍未覆盖 `docs/ALGORITHM_AUDIT.md` 和 `docs/TECHNICAL.md`。建议未来扩展 sync_check 到文档层（当前以人工同步为主，已在 §2.3 中记录）。
