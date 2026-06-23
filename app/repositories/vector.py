"""Milvus 通用向量数据访问层。

``VectorRepository`` 绑定单个 collection，封装 collection 生命周期、批量写入、
删除、标量查询和向量检索。业务层只接触普通字典与 ``VectorSearchHit``，不依赖
PyMilvus 的返回对象，也不得自行创建客户端。
"""
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, TypeVar

from app.core.logger import logger
from app.core.milvus import get_milvus, get_milvus_settings
from app.exceptions import (
    MILVUS_ERRNO_INVALID_RESPONSE,
    MILVUS_ERRNO_OPERATION_FAILED,
    BizException,
)
from app.schemas.vector import VectorSearchHit


ResultT = TypeVar("ResultT")


class VectorRepository:
    """绑定一个 Milvus collection 的通用异步 Repository。

    Args:
        collection_name: collection 名称，不能为空。
        batch_size: insert/upsert 单批实体数；未传时读取 Milvus 全局配置。
    """

    def __init__(self, collection_name: str, batch_size: int | None = None) -> None:
        name = collection_name.strip()
        if not name:
            raise BizException(
                message="Milvus collection 名称不能为空",
                errno=MILVUS_ERRNO_OPERATION_FAILED,
            )

        settings = get_milvus_settings()
        resolved_batch_size = settings.batch_size if batch_size is None else batch_size
        if resolved_batch_size <= 0:
            raise BizException(
                message="Milvus batch_size 必须大于 0",
                errno=MILVUS_ERRNO_OPERATION_FAILED,
            )

        self.collection_name = name
        self.batch_size = resolved_batch_size
        self.timeout = settings.timeout

    async def _call(
        self,
        operation: str,
        call: Callable[..., Awaitable[ResultT]],
        **kwargs: Any,
    ) -> ResultT:
        """执行一次 SDK 操作并统一转换异常，不记录实体或向量内容。"""
        try:
            return await call(**kwargs)
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001 —— PyMilvus 异常类型随传输层变化
            logger.error(
                "Milvus 操作失败 | operation={} | collection={} | reason_type={}",
                operation,
                self.collection_name,
                exc.__class__.__name__,
            )
            raise BizException(
                message=f"Milvus {operation} 操作失败",
                errno=MILVUS_ERRNO_OPERATION_FAILED,
            ) from exc

    def _client_method(self, name: str) -> Callable[..., Awaitable[Any]]:
        """从当前健康客户端获取 SDK 方法，避免长期持有已关闭客户端。"""
        return getattr(get_milvus(), name)

    @staticmethod
    def _invalid_response(message: str) -> BizException:
        """构造统一的 SDK 响应结构异常。"""
        return BizException(message=message, errno=MILVUS_ERRNO_INVALID_RESPONSE)

    async def create_collection(
        self,
        dimension: int,
        *,
        primary_field: str = "id",
        vector_field: str = "vector",
        metric_type: str = "COSINE",
        auto_id: bool = False,
        consistency_level: str = "Bounded",
    ) -> None:
        """按常用向量 collection 契约创建 collection。"""
        if dimension <= 0:
            raise BizException(
                message="Milvus 向量维度必须大于 0",
                errno=MILVUS_ERRNO_OPERATION_FAILED,
            )
        await self._call(
            "create_collection",
            self._client_method("create_collection"),
            collection_name=self.collection_name,
            dimension=dimension,
            primary_field_name=primary_field,
            vector_field_name=vector_field,
            metric_type=metric_type,
            auto_id=auto_id,
            consistency_level=consistency_level,
            timeout=self.timeout,
        )

    async def drop_collection(self) -> None:
        """删除当前 collection。"""
        await self._call(
            "drop_collection",
            self._client_method("drop_collection"),
            collection_name=self.collection_name,
            timeout=self.timeout,
        )

    async def has_collection(self) -> bool:
        """判断当前 collection 是否存在。"""
        return await self._call(
            "has_collection",
            self._client_method("has_collection"),
            collection_name=self.collection_name,
            timeout=self.timeout,
        )

    async def load_collection(self) -> None:
        """将当前 collection 加载到查询节点。"""
        await self._call(
            "load_collection",
            self._client_method("load_collection"),
            collection_name=self.collection_name,
            timeout=self.timeout,
        )

    async def release_collection(self) -> None:
        """从查询节点释放当前 collection。"""
        await self._call(
            "release_collection",
            self._client_method("release_collection"),
            collection_name=self.collection_name,
            timeout=self.timeout,
        )

    async def _write(
        self,
        operation: str,
        data: Sequence[dict[str, Any]],
        count_field: str,
    ) -> int:
        """按配置分批写入并严格汇总 SDK 计数。"""
        rows = list(data)
        if not rows:
            return 0

        total = 0
        for offset in range(0, len(rows), self.batch_size):
            batch = rows[offset : offset + self.batch_size]
            response = await self._call(
                operation,
                self._client_method(operation),
                collection_name=self.collection_name,
                data=batch,
                timeout=self.timeout,
            )
            if not isinstance(response, Mapping):
                raise self._invalid_response(f"Milvus {operation} 响应不是字典")
            count = response.get(count_field)
            if not isinstance(count, int) or count < 0:
                raise self._invalid_response(
                    f"Milvus {operation} 响应缺少有效 {count_field}"
                )
            total += count

        logger.info(
            "Milvus 批量写入完成 | operation={} | collection={} | count={} | batches={}",
            operation,
            self.collection_name,
            total,
            (len(rows) + self.batch_size - 1) // self.batch_size,
        )
        return total

    async def insert(self, data: Sequence[dict[str, Any]]) -> int:
        """分批新增实体并返回 SDK 确认的总写入数。"""
        return await self._write("insert", data, "insert_count")

    async def upsert(self, data: Sequence[dict[str, Any]]) -> int:
        """分批新增或更新实体并返回 SDK 确认的总写入数。"""
        return await self._write("upsert", data, "upsert_count")

    async def delete(
        self,
        *,
        ids: list[int | str] | int | str | None = None,
        filter: str | None = None,
    ) -> int:
        """按主键或过滤表达式删除实体，两种选择器必须且只能提供一种。"""
        has_ids = ids is not None and (not isinstance(ids, list) or bool(ids))
        has_filter = filter is not None and bool(filter.strip())
        if has_ids == has_filter:
            raise BizException(
                message="Milvus 删除必须且只能提供 ids 或 filter",
                errno=MILVUS_ERRNO_OPERATION_FAILED,
            )

        kwargs: dict[str, Any] = {
            "collection_name": self.collection_name,
            "timeout": self.timeout,
        }
        if has_ids:
            kwargs["ids"] = ids
        else:
            kwargs["filter"] = filter

        response = await self._call(
            "delete", self._client_method("delete"), **kwargs
        )
        if not isinstance(response, Mapping):
            raise self._invalid_response("Milvus delete 响应不是字典")
        count = response.get("delete_count")
        if not isinstance(count, int) or count < 0:
            raise self._invalid_response("Milvus delete 响应缺少有效 delete_count")
        return count

    async def get(
        self,
        ids: list[int | str] | int | str,
        *,
        output_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """按主键读取实体。"""
        return await self._call(
            "get",
            self._client_method("get"),
            collection_name=self.collection_name,
            ids=ids,
            output_fields=output_fields,
            timeout=self.timeout,
        )

    async def query(
        self,
        filter: str,
        *,
        output_fields: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """执行 Milvus 标量过滤查询。"""
        kwargs: dict[str, Any] = {
            "collection_name": self.collection_name,
            "filter": filter,
            "output_fields": output_fields,
            "timeout": self.timeout,
        }
        if limit is not None:
            if limit <= 0:
                raise BizException(
                    message="Milvus query limit 必须大于 0",
                    errno=MILVUS_ERRNO_OPERATION_FAILED,
                )
            kwargs["limit"] = limit
        return await self._call(
            "query", self._client_method("query"), **kwargs
        )

    async def search(
        self,
        vectors: Sequence[Sequence[float]],
        *,
        anns_field: str = "vector",
        filter: str = "",
        limit: int = 10,
        output_fields: list[str] | None = None,
        search_params: dict[str, Any] | None = None,
    ) -> list[list[VectorSearchHit]]:
        """执行向量检索并按查询向量分组返回归一结果。"""
        data = [list(vector) for vector in vectors]
        if not data:
            return []
        if limit <= 0:
            raise BizException(
                message="Milvus search limit 必须大于 0",
                errno=MILVUS_ERRNO_OPERATION_FAILED,
            )

        response = await self._call(
            "search",
            self._client_method("search"),
            collection_name=self.collection_name,
            data=data,
            anns_field=anns_field,
            filter=filter,
            limit=limit,
            output_fields=output_fields,
            search_params=search_params,
            timeout=self.timeout,
        )
        return self._normalize_search_response(response)

    def _normalize_search_response(
        self, response: Any
    ) -> list[list[VectorSearchHit]]:
        """严格校验并归一 PyMilvus 的分组检索响应。"""
        if not isinstance(response, list):
            raise self._invalid_response("Milvus search 响应不是分组列表")

        normalized: list[list[VectorSearchHit]] = []
        for group in response:
            if not isinstance(group, list):
                raise self._invalid_response("Milvus search 命中分组不是列表")
            normalized_group: list[VectorSearchHit] = []
            for hit in group:
                if not isinstance(hit, Mapping):
                    raise self._invalid_response("Milvus search 命中不是字典")
                if hit.get("id") is None or hit.get("distance") is None:
                    raise self._invalid_response(
                        "Milvus search 命中缺少 id 或 distance"
                    )
                entity = hit.get("entity", {})
                if not isinstance(entity, Mapping):
                    raise self._invalid_response("Milvus search entity 不是字典")
                try:
                    normalized_group.append(
                        VectorSearchHit(
                            id=hit["id"],
                            distance=float(hit["distance"]),
                            entity=dict(entity),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    raise self._invalid_response(
                        "Milvus search 命中字段类型非法"
                    ) from exc
            normalized.append(normalized_group)
        return normalized
