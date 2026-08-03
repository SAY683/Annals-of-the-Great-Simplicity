# ROUND33 元思考与经验归档

**日期**: 2026-08-03
**阶段**: E（直接底层算法分析）+ F（反向传播侦察）+ G（论文更新+同步+归档）
**前序**: ROUND32（Gavish-Donoho β<0.1 极限值修复 + 12维度交叉验证）

---

## 一、工作概览

### 1.1 任务起点
- 用户要求"全量推进，下一轮"，参考 `F:\攻略\命令文本2.txt` 执行缜密计划
- 命令文本2.txt 核心要点：30+40条杜撰新闻、trace-engine-web→trace-to-edm→edm-takens-web 管道、数学家/算法工程师/架构师三视角并行、论文撰写、便携目录同步

### 1.2 完成项

| 编号 | 任务 | 状态 | 关键产出 |
|------|------|------|----------|
| E1 | 直接底层算法分析（绕过 game-log hack） | ✅ 完成 | round33_e_direct_analysis.py + 3个JSON结果 |
| E2 | 三视角验证矩阵 | ✅ 完成 | round33_e_three_perspectives.json |
| E3 | 架构债务识别 | ✅ 完成 | DEBT-ROUND33-01 (game-log schema 硬编码) |
| F1 | 反向传播侦察 | ✅ 完成 | ROUND33_F_AUDIT.md |
| F2 | 各阶段元实现审计 | ✅ 完成 | ROUND33_F_AUDIT.md |
| G1 | 论文更新 v1.1 | ✅ 完成 | 五大项目算法模型论文.md 第9章 |
| G2 | 经验归档 | ✅ 进行中 | 本文件 |
| G3 | 便携目录同步 | 待执行 | round33_e_direct_analysis.py + 审计报告 + 论文 |

---

## 二、核心发现：consensus_score → ate 真实因果信号

### 2.1 发现过程

1. **初始状态**: edm-takens-web 在 8002 端口运行，30news 分析已完成（results/1785734445_6772d374/）
2. **异常识别**: 检查 config_1785734463.json 发现 `target_col="result"`，但 params 显示原始请求是 `target_col="ate"`；列名是 `result/kills/damage/deaths` 而非 `ate/ate_ci_lower/ate_ci_upper/adj_density`
3. **根因定位**: file_management.py:_prepare_pipeline_data (line 163-231) 强制重映射列名到 game-log schema
4. **后果分析**: pipeline.py 的 CCM 只测试 `kills→result, damage→result, deaths→result`，即 CI 边界→ate（数学恒等式，ρ=0.956 是 CI 定义必然，无科学价值）；HAVOK 因共线退化（r=2, degenerate=true）
5. **绕过方案**: 写 round33_e_direct_analysis.py 直接调用 ccm_causality_test + SovereignHAVOK，测试真实因果对
6. **真实发现**: consensus_score → ate 显著（30news ρ=0.788 dominant, 40news ρ=0.616 convergent）

### 2.2 科学意义

- `consensus_score = 1 - std(norm(ATE, CCM, CausalLearn))` 是 trace-to-edm 计算的元 SCM 参数
- 它驱动 ATE 说明：三方因果算法（DoWhy/CCM/CausalLearn）共识度越高，ATE 估计值越大
- 语义合理：共识高=信号强=因果效应估计值大
- 这是元 SCM 设计的价值证明，但长期被 game-log hack 掩盖

---

## 三、盲区识别与反思

### 3.1 关键盲区：game-log schema 硬编码长期未识别（P0 级元反思）

**事件**: edm-takens-web 的 file_management.py:_prepare_pipeline_data 自项目初期就存在 game-log schema 硬编码，把用户列名强制重映射到 result/kills/damage/deaths。对88列轨迹数据严重破坏语义，但长期未识别。

**盲区根因**:
1. **结果"看起来正常"**: 分析结果有 ρ 值、有 verdict、有 audit_verdict，表面上完整。实际上 ρ=0.956 是 CI 边界与 ate 的数学恒等式必然，非真实因果发现
2. **column_mapping 字段被忽视**: result.json 的 summary.column_mapping 明确记录了 `result←ate, kills←ate_ci_lower, damage←ate_ci_upper, deaths←adj_density`，但未触发警觉
3. **架构债务的"隐身性"**: game-log schema 是项目初期的合理设计（pipeline.py 硬编码 game-log 列名），但随着项目演进到88列轨迹数据，该设计变成债务却未被重新审视
4. **单一视角的局限**: 如果只从"算法工程师"视角看，CCM 实现正确（有收敛检查、有种子确定性）；只从"数学家"视角看，HAVOK 公式正确（Gavish-Donoho 4/√3）。只有"架构师"视角能发现数据流语义破坏

**经验沉淀**:
> **分析结果的"完整性"不等于"正确性"**。有 ρ 值、有 verdict、有 audit 通过，不代表分析的是正确的变量对。必须验证：(1) 输入列名的语义是否被保留；(2) CCM 测试的因果对是否有科学意义；(3) 高 ρ 值是否是数学恒等式的必然结果（如 CI 边界→估计值）。

### 3.2 盲区：consensus_score 的因果信号被掩盖

**事件**: consensus_score 是 trace-to-edm 计算的元 SCM 参数，反映三方因果算法共识度。它驱动 ATE 是一个有实际科学意义的发现，但被 game-log hack 完全掩盖（pipeline.py 的 CCM 只测试 kills/damage/deaths → result，漏掉 consensus_score）。

**盲区根因**:
1. **元 SCM 计算列的价值被低估**: consensus_score 不是 TRACE 直接输出，而是 trace-to-edm 的计算列，其因果意义容易被忽视
2. **CCM 测试对的选择偏见**: pipeline.py 硬编码测试 kills/damage/deaths → result，这些是 game-log 的"标准"因果对，但对88列轨迹数据不适用
3. **直接调用底层算法的必要性**: 只有绕过 pipeline.py 的 game-log 适配层，直接调用 ccm_causality_test，才能测试任意因果对

**经验沉淀**:
> **元 SCM 计算列可能有重要因果意义**。consensus_score 这类计算列（非直接观测变量）可能捕获了算法间的元一致性信号，是值得 CCM 测试的因果对。架构债务修复时，应确保 CCM 测试对的选择不被硬编码限制。

### 3.3 叙事化修缮的再次警惕

**事件**: ROUND32 声称修复 Gavish-Donoho β<0.1 极限值，但 ROUND33 三视角验证发现实际已落地（4/√3）。这次验证通过源码审计 + 数学家视角交叉确认，非"信任声明"。

**盲区根因**:
1. **声明与落地的差距**: ROUND32 的归档声称"已修复"，但需要 ROUND33 的源码审计才能确认真实落地
2. **元审计的必要性**: 每轮声称的"修复"必须在下一轮通过源码审计验证，不能"自我声明"

**经验沉淀**:
> **修复声明必须在下一轮通过源码审计验证**。任何"已完成"声明都必须经过独立的源码审计确认，不能信任自我声明。三视角验证矩阵（数学家/算法工程师/架构师）是有效的交叉验证机制。

### 3.4 P0级便携目录同步遗漏（本轮最严重盲区）

**事件**: ROUND33-G3 便携目录同步阶段发现：
- `Skill/edm-takens-web/backend/edmtakens/sovereign_havok.py` 仍是旧的 1.5494（非 4/√3）
- `Skill/edm-takens-web/backend/edmtakens/ccm_causality.py` 无自适应步长/hashlib.md5修复
- `Skill/edm-takens/src/sovereign_havok.py` 同样未同步
- `Skill/edm-takens/src/ccm_causality.py` 同样未同步

**盲区根因**:
1. **开发目录 ≠ 便携目录**: ROUND32 在开发目录修复了算法，但未同步到便携目录的 4 个副本（edm-takens-web + edm-takens 各 2 份）
2. **三视角验证只在开发目录执行**: ROUND33-E 的三视角验证只检查了开发目录的源码，未检查便携目录
3. **同步验证的盲区**: verify_portable.py 和 sync_check.py 未包含算法层修复的 SHA256 一致性检查（只检查结构契约，不检查算法实现一致性）

**已采取的修复**:
- 立即同步 sovereign_havok.py 和 ccm_causality.py 到 4 个便携目录副本
- 验证落地：4 个副本均已确认 4/√3 + 自适应步长 + hashlib.md5

**经验沉淀**:
> **算法层修复必须同步到所有便携目录副本，并通过源码审计验证落地**。三视角验证不能只在开发目录执行，必须扩展到便携目录。建议下一轮在 sync_check.py 中新增算法层关键文件的 SHA256 一致性检查（sovereign_havok.py + ccm_causality.py），确保开发目录与便携目录的算法实现完全一致。

---

## 四、元思考纪律

### 4.1 代码审查先于功能测试
本轮通过静态代码审计发现 game-log hack，比运行时测试更早定位问题。如果直接信任运行时结果（有 ρ 值、有 verdict），会错过架构债务。

### 4.2 三视角并行评审，不统一判定
- 数学家：验证 Gavish-Donoho 公式（PASS:2）
- 算法工程师：验证 CCM 收敛性 + 种子确定性（PASS:3）
- 架构师：验证数据流 + 端口 + 列契约（PASS:3, DEBT:1）

三个视角不统一判定，防止任一视角的盲区污染整体判断。架构师视角发现了 game-log hack，这是数学家和算法工程师视角无法发现的。

### 4.3 交叉验证：直接调用 vs pipeline.py 路径
通过对比直接调用底层算法和 pipeline.py 路径的结果，揭示架构债务：
- 直接调用：HAVOK r=9/12, non-degenerate
- pipeline.py：HAVOK r=2, degenerate
- 差异原因：game-log hack 导致 CI 边界与 ate 共线

### 4.4 警惕上下文，不盲信"已完成"声明
ROUND32 声称修复 Gavish-Donoho，ROUND33 通过源码审计验证落地。不盲信上下文中的"已完成"声明，必须通过独立验证确认。

---

## 五、修缮清单

### 5.1 本轮已修缮（真实落地，非叙事化）

| 编号 | 文件 | 修缮内容 | 验证方式 |
|------|------|----------|----------|
| R33-01 | edm-takens-web/round33_e_direct_analysis.py | 新建直接底层算法分析脚本 | 执行成功，输出3个JSON |
| R33-02 | edm-takens-web/ROUND33_F_AUDIT.md | 新建反向传播侦察审计报告 | 内容完整，包含DEBT-ROUND33-01 |
| R33-03 | Docs/五大项目算法模型论文/五大项目算法模型论文.md | 修正83列→88列，新增第9章ROUND33更新 | 内容完整，包含真实因果发现+架构债务披露+三视角验证 |
| R33-04 | Docs/META_THINKING/ROUND33_META_THINKING.md | 本文件，经验归档 | 内容完整 |

### 5.2 本轮识别但未修（架构债务，下一轮候选）

| 编号 | 文件 | 债务内容 | 修复建议 |
|------|------|----------|----------|
| DEBT-ROUND33-01 | edm-takens-web/backend/services/file_management.py | game-log schema 硬编码 (line 163-231) | 重构 pipeline.py 支持任意列名 |
| DEBT-ROUND33-02 | edm-takens-web/backend/edmtakens/pipeline.py | 硬编码 ['result','kills','damage','deaths'] (line 166/168/634/899) | 移除 game-log 硬编码，支持动态列名 |
| DEBT-ROUND33-03 | trace-engine-web | replay 模式输出同质化 (edge_count/refuted_count 常量) | 检查 replay 模式是否正确恢复 DEEP 分析的变量性 |

---

## 六、三视角验证结果汇总

### 6.1 数学家视角
- Gavish-Donoho β<0.1 极限值 = 4/√3 ≈ 2.3094 ✅ PASS
- Gavish-Donoho 阈值维度 = max(m,n) ✅ PASS
- **结论**: HAVOK 数学实现正确，ROUND32 修复已真实落地

### 6.2 算法工程师视角
- CCM lib_sizes 自适应步长 ✅ PASS
- CCM surrogate 种子 hashlib.md5 确定性 ✅ PASS
- CCM disclaimer_level 阈值 >= 2 ✅ PASS
- **结论**: CCM 实现收敛性诊断完整，可重现性保证

### 6.3 架构师视角
- game-log schema 硬编码 ⚠️ DEBT-ACKNOWLEDGED
- 端口环境变量驱动 ✅ PASS
- 30news 列契约 (88列) ✅ PASS
- 40news 列契约 (88列) ✅ PASS
- **结论**: 数据流链路完整，但 edm-takens-web 内部存在已知架构债务

---

## 七、下一轮输入（ROUND34 候选）

### 7.1 P0 级候选
1. **DEBT-ROUND33-01 修复**: 重构 pipeline.py 支持任意列名，移除 game-log schema 硬编码
2. **DEBT-ROUND33-02 修复**: 移除 pipeline.py 的 ['result','kills','damage','deaths'] 硬编码，支持动态列名
3. **DEBT-ROUND33-03 调查**: 检查 trace-engine-web replay 模式为何输出同质化数据（edge_count/refuted_count 常量）

### 7.2 P1 级候选
1. **便携目录同步**: 同步 round33_e_direct_analysis.py + ROUND33_F_AUDIT.md + 论文到便携目录
2. **CCM 测试对扩展**: 在 pipeline.py 修复后，扩展 CCM 测试对到 consensus_score/max_delta_nll/concept_coverage 等真实因果变量
3. **HAVOK 多时序分析**: 对 consensus_score/max_delta_nll/concept_coverage 时序做 HAVOK 动力学重构

### 7.3 P2 级候选
1. **样本量扩展**: 100+ 条新闻的端到端测试，验证 consensus_score → ate 因果性的样本量稳定性
2. **SUPER 模式 L3 验证**: SUPER 模式相关结论从 L1 代码阅读升级到 L3 运行时验证
3. **IAAFT 替代数据**: 对 consensus_score → ate 做 IAAFT 替代数据显著性检验

---

## 八、元反思的元反思

### 8.1 本轮元反思的盲区
1. **是否过度聚焦 game-log hack?** 本轮发现 game-log hack 后，大量篇幅围绕它展开。是否忽略了其他潜在问题？下一轮应主动检查：(a) trace-engine-web 的 DEEP/SUPER 模式实现；(b) trace-to-edm 的 Layer 2/3 计算；(c) edm-takens-web 的其他端点
2. **直接调用底层算法的代表性?** round33_e_direct_analysis.py 只测试了6个因果对，是否遗漏了其他有意义的因果对？下一轮应扩展到所有88列中的数值列两两测试
3. **三视角验证的充分性?** 本轮三视角验证主要针对 HAVOK 和 CCM 的已知修复点。是否应该对未修复的部分（如 Simplex/S-Map/Lyapunov）也做验证？

### 8.2 元思考纪律的自我审查
- ✅ 代码审查先于功能测试：通过静态审计发现 game-log hack
- ✅ 三视角并行评审：数学家/算法工程师/架构师不统一判定
- ✅ 交叉验证：直接调用 vs pipeline.py 路径对比
- ✅ 警惕上下文：ROUND32 声明通过 ROUND33 源码审计验证
- ⚠ 应优尽优：game-log hack 识别后未立即修复（标记为下一轮候选），是否违反"应修尽修"原则？决策依据是修复需要大改 pipeline.py，属于架构调整，需用户确认

---

> **归档完成时间**: 2026-08-03
> **核心结论**: 算法层健康，适配层存在已知架构债务（DEBT-ROUND33-01）
> **真实因果发现**: consensus_score → ate (ρ=0.788/0.616, dominant/convergent)
> **元思考纪律**: 代码审查先于功能测试 + 三视角并行 + 交叉验证 + 警惕上下文
