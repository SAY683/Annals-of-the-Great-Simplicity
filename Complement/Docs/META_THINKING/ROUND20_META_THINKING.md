# 元思考归档 — Round 20

> 创建: 2026-07-27
> 性质: Round 20 循环核查的元思考归档, 聚焦 PM 视角审视与跨项目一致性
> 关联: ROUND19_META_THINKING.md / META_AUDIT_CHANGELOG.md §20

---

## 1. 缓存戳不一致的根因分析

### 1.1 Round 19 遗留问题

Round 19 已识别缓存戳三方不一致 (20260725f / 20260727c / 20260727d 混用), 并"统一"为 20260727d。但 Round 20 审视发现:

- **edm-takens-web**: CSS `?v=20260727d` ✓
- **trace-engine-web**: CSS `?v=20260727d` 但 JS `?v=20260727c` ✗ (内部不一致)
- **trace-to-edm**: CSS `?v=20260727c` 但 JS `?v=20260727d` ✗ (内部不一致, 且与 trace-engine-web 相反)

### 1.2 根因

Round 19 只统一了 CSS 缓存戳, 漏掉了 JS 缓存戳。且 trace-to-edm 的 CSS 缓存戳根本没更新到 d, 仍停留在 c。

### 1.3 元教训

1. **"统一"操作必须全量扫描**: 用 `grep v=2026072` 而非记忆中的"应该改过了"
2. **CSS 和 JS 是两条独立链**: 修 CSS 时容易忘记 JS, 反之亦然
3. **缓存戳应该有自动化机制**: 人工维护必然出错, 未来应从 package.json version 字段自动注入

### 1.4 Round 20 修复

全部统一为 `?v=20260727e` (Round 20 修缮版本), 用 Grep 全量验证无遗漏。

---

## 2. z-index 层级体系的跨项目统一

### 2.1 Round 19 建立的层级

| 层级 | z-index | 用途 |
|------|---------|------|
| CRT overlay | 999 | 扫描线特效 |
| SUPER 模式脉冲边框 | 9998 | 全屏边框动画 |
| modal-overlay | 10000 | 模态框遮罩 |
| toast | 10001 | 顶部提示 (最高) |

### 2.2 Round 20 发现的违反

- **edm-takens-web**: `.modal { z-index: 100 }` (远低于 10000), `.quality-detail-modal { z-index: 200 }` (低于 SUPER 边框 9998)
- **trace-engine-web**: `.modal-overlay { z-index: 9999 }` (与 SUPER 边框 9998 太近, 可能冲突)

### 2.3 修复

- edm-takens-web `.modal`: 100 → 10000
- edm-takens-web `.quality-detail-modal`: 200 → 10001 (作为子模态, 高于主模态)
- trace-engine-web `.modal-overlay`: 9999 → 10000

### 2.4 元教训

z-index 层级体系建立后, 必须用 Grep 全项目扫描所有 `z-index:` 声明, 确认无违反。仅靠记忆中的"应该都改了"不可靠。

---

## 3. 移动端断点不统一的现状

### 3.1 三方断点分布

| 项目 | 断点 | 问题 |
|------|------|------|
| edm-takens-web | 900px / 768px / 520px | 768px 覆盖 900px 的部分规则 (h2 居中丢失) |
| trace-engine-web | 768px / 480px | **缺少 900px 断点**, 平板尺寸下仍双栏 |
| trace-to-edm | 900px / 720px / 520px | 720px 是中间断点, 与其他项目不统一 |

### 3.2 Round 20 修复

- edm-takens-web 768px 断点: 移除 `text-align: left` 和 `font-size: 0.66rem`, 保持与 900px 一致的居中对齐
- edm-takens-web 768px 断点: 移除激进的 `button { width: 100% }`, 改为仅对主操作按钮全宽

### 3.3 待修复 (较大改动, 记录待后续 Round)

- trace-engine-web 需补 900px 断点 (目前 768-900px 范围内仍双栏)
- trace-to-edm 的 720px 断点是否应改为 768px 以统一
- 三方是否应统一为 900px / 768px / 520px 三级断点

---

## 4. PM 视角审视方法论

### 4.1 PM 视角 vs 开发者视角

**开发者视角**: "功能是否实现? 代码是否正确?"
**PM 视角**: "用户能否理解? 操作是否流畅? 界面是否美观?"

### 4.2 Round 20 PM 视角发现清单

| 编号 | 问题 | PM 影响 | 修复状态 |
|------|------|---------|---------|
| PM-01 | 缓存戳不一致导致旧样式缓存 | 用户看到错乱界面 | ✅ 已修复 |
| PM-02 | z-index 层级冲突 | 模态框被遮挡, 用户无法操作 | ✅ 已修复 |
| PM-03 | status-wall display:none | 整面墙消失, 布局跳动 | ✅ 已修复 (opacity 0.5) |
| PM-04 | 768px 断点 h2 左对齐 | 移动端标题居中丢失, 与桌面端不一致 | ✅ 已修复 |
| PM-05 | button width:100% 过激进 | 关闭按钮(✕)被撑满, 视觉突兀 | ✅ 已修复 |
| PM-06 | stat-label 0.52rem 字号过小 | 低于 WCAG 可读标准 | ✅ 已修复 (0.6rem) |
| PM-07 | SECTOR-A5 标题结构不一致 | 多余 wrapper 可能导致样式偏差 | ✅ 已修复 |
| PM-08 | trace-engine-web 缺 900px 断点 | 平板尺寸下双栏挤压 | 待修复 |
| PM-09 | trace-to-edm 内联样式过多 | 维护困难, 难以统一主题 | 待评估 |
| PM-10 | select option 字号不一致 | 视觉不协调 | 待修复 |

### 4.3 元教训

PM 视角审视的核心是 "陌生人漫游": 假设用户从未见过这个界面, 能否在 30 秒内理解每个区域的功能? 能否在不出错的情况下完成一次完整流程? 这要求:
1. **视觉一致性**: 相同功能的元素必须有相同的视觉表现
2. **状态可见性**: 空状态不能完全消失, 应弱化显示并提示
3. **触控目标**: 移动端按钮 ≥44px, 桌面端 ≥32px
4. **字号可读性**: 最小字号 ≥0.6rem (9.6px), 低于此值需特殊理由

---

## 5. status-wall awaiting-data 的设计哲学

### 5.1 问题

trace-engine-web 用 `display: none` 完全隐藏空状态墙, edm-takens-web 用 `opacity: 0.5` 弱化显示。

### 5.2 设计哲学

- **display:none**: 布局干净, 但有历史分析时整面墙消失, 用户失去上下文
- **opacity:0.5**: 保留布局结构, 用户能看到"这里有状态墙, 只是当前无数据", 认知负担更低

### 5.3 元教训

空状态处理的核心是 "保留结构, 弱化内容", 而非 "完全隐藏"。这与 Material Design 的 "skeleton screen" 思想一致: 让用户知道"这里会有东西", 而非"这里什么都没有"。

---

## 6. 总结: Round 20 的元思考贡献

1. **"统一"操作必须全量扫描**: 不能只改记得的部分, 必须用 Grep 验证无遗漏
2. **z-index 层级需要跨项目治理**: 单项目内的层级正确不等于跨项目一致
3. **PM 视角 = 陌生人漫游**: 假设用户从未见过界面, 能否快速理解和操作
4. **空状态保留结构**: 用 opacity 弱化, 而非 display:none 隐藏

**下一步应用**: Round 21 应聚焦 trace-engine-web 的 900px 断点补全, 以及三方断点的最终统一方案。
