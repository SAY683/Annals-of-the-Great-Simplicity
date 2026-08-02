"""Numeric constants for EDM-Takens modules.

P2-1 修复 (ROUND26 算法审视 + 科研严谨性审查 Round 27):
统一散布在 10+ 文件的 73 处硬编码 eps (1e-12, 1e-15, 1e-10, 1e-24),
消除同一物理量在不同代码路径用不同 eps 导致的边界情况判定差异.

分类依据 (基于数值计算的上下文):
- EPS_DISTANCE: 距离零值过滤 (1e-15, 接近 float64 机器精度 ~2.2e-16)
- EPS_VARIANCE: 方差/标准差防护 (1e-12, 适合标准化数据)
- EPS_PROB: 概率平滑 + log 分母 (1e-12, 适合 N<=1000 样本)
- EPS_ENERGY: 总能量防护 (1e-24, sum(s^2) 累积阈值)
- EPS_LYAPUNOV: Lyapunov 发散距离阈值 (1e-12, log 取值下界)
"""
EPS_DISTANCE = 1e-15
EPS_VARIANCE = 1e-12
EPS_PROB = 1e-12
EPS_ENERGY = 1e-24
EPS_LYAPUNOV = 1e-12
