"""向量数据库的厂商无关数据模型。"""
from typing import Any

from pydantic import BaseModel, Field


class VectorSearchHit(BaseModel):
    """单条向量检索命中。

    Attributes:
        id: collection 主键，兼容整数与字符串主键。
        distance: Milvus 返回的距离或相似度分数，含义由 metric_type 决定。
        entity: 调用方通过 output_fields 请求的标量字段。
    """

    id: int | str
    distance: float
    entity: dict[str, Any] = Field(default_factory=dict)
