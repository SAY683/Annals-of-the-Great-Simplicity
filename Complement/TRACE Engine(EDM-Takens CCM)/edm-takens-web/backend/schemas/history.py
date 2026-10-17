"""Pydantic request schemas for history endpoints."""
from typing import List, Optional

from pydantic import BaseModel, Field


class BatchRequest(BaseModel):
    """batch_history 端点的请求体模型. 兼容 ids 旧字段名."""
    action: str = Field(..., description="操作类型: archive|delete|download")
    task_ids: Optional[List[str]] = Field(None, min_items=1, description="任务 ID 列表, 至少 1 个")
    ids: Optional[List[str]] = Field(None, min_items=1, description="task_ids 的旧别名")

    def normalized_ids(self) -> List[str]:
        """返回有效的 task_ids, 优先 task_ids 字段, 回退到 ids."""
        return self.task_ids if self.task_ids else (self.ids or [])


class CompareRequest(BaseModel):
    """compare_tasks 端点的请求体模型.

    P1 修复 (Round 24 §3): 取消 max_items=2 限制, 支持 2-8 个任务的对比,
    前端按数量动态渲染对比网格. 仍保留 min_items=2 保证至少有对比意义.
    """
    task_ids: List[str] = Field(..., min_items=2, max_items=8, description="任务 ID 列表, 2-8 个")
