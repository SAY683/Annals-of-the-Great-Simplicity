"""
trace-to-edm: 三层元因果控制论桥接系统

将 TRACE 引擎（文本→因果图）与 EDM-Takens（CSV→动力学预测）
串联为数据闭环，实现从文本到相变预警的完整管线。

三层架构:
  Layer 1 — Meta-SCM Parameters:  从 TRACE result.json 提取系统诊断不变量
  Layer 2 — Secular Semantic Proj: PCA 驱动的世俗语义流形投影
  Layer 3 — Sacred Axis Audit:     八正道神圣坐标轴的零样本探针对齐

用法:
  from trace_to_edm.bridge import process_single_text
  row = process_single_text("一篇文本...", "2026-07-17 10:00")
"""

__version__ = "0.1.0"
__description__ = "Meta-Causal Cybernetics Bridge: TRACE → EDM-Takens"
