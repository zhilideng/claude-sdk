"""LLM 测试 API 路由（v1）。

仅用于验证已配置 Provider 的连通性与基础响应，不承载正式业务编排。
"""
from typing import Any

import openai
from fastapi import APIRouter, Query, Request

from app.core.config import get_settings
from app.core.llm.gateway import get_llm
from app.exceptions import BizException, LLM_ERRNO_CALL_FAILED
from app.utils.common import ApiResponse

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/zhipu/test")
async def test_zhipu_llm(
    request: Request,
    prompt: str = Query("只回复两个字：成功", min_length=1, max_length=500),
    max_tokens: int = Query(32, ge=1, le=512),
) -> dict[str, Any]:
    """测试智谱 LLM Provider 是否可用。

    密钥由 ``LLM_API_KEY_ZHIPU`` 注入，接口不接收也不回显任何密钥。
    """
    settings = getattr(request.app.state, "settings", None) or get_settings()
    cfg = settings.llm.providers.get("zhipu")
    if cfg is None:
        raise BizException("智谱 LLM Provider 未配置", errno=LLM_ERRNO_CALL_FAILED)

    client = get_llm("zhipu")
    try:
        response = await client.chat.completions.create(
            model=cfg.default_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
    except openai.AuthenticationError as exc:
        raise BizException(
            "智谱 LLM 鉴权失败，请检查 LLM_API_KEY_ZHIPU 是否正确并已在服务进程中生效",
            errno=LLM_ERRNO_CALL_FAILED,
        ) from exc
    except openai.APIStatusError as exc:
        raise BizException(
            f"智谱 LLM 调用失败（HTTP {exc.status_code}）",
            errno=LLM_ERRNO_CALL_FAILED,
        ) from exc
    except Exception as exc:  # noqa: BLE001 —— 外部模型调用失败统一转业务异常
        raise BizException("智谱 LLM 调用失败", errno=LLM_ERRNO_CALL_FAILED) from exc

    message = response.choices[0].message.content if response.choices else ""
    usage = response.usage.model_dump() if response.usage is not None else None
    return ApiResponse.ok(
        {
            "provider": "zhipu",
            "model": cfg.default_model,
            "content": message,
            "usage": usage,
        }
    ).to_payload()
