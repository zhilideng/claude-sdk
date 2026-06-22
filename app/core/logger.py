"""结构化日志（基于 loguru）。

提供全局 logger、setup_logging 与 intercept_uvicorn_logs：
- setup_logging：配 3 个 sink（stdout 全量 / app.log 全量 / error.log ERROR 分流），
  全环境统一人类可读单行格式（项目不接外部日志采集，JSON 序列化无收益故 YAGNI；
  将来接 ELK/Loki 再考虑加结构化 sink）。
  生产 diagnose=False 防异常栈泄露敏感变量。
- intercept_uvicorn_logs：把 uvicorn 标准库 logging 接入 loguru，使应用日志与
  uvicorn 访问/错误日志格式统一，便于生产排查。
"""
import logging
import sys
from pathlib import Path

from loguru import logger

from app.core.settings import LoggingSettings

# 默认日志格式：时间 | 级别 | 模块:函数:行号 [req_id=xxx] | 消息
# req_id 由 patcher 从请求上下文（ContextVar）注入，请求外为占位 "-"
_DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>[req_id={extra[request_id]}]</level> | "
    "<level>{message}</level>"
)

# 第三方库「噪音」logger 清单：这些库底层经标准库 logging 在 DEBUG/INFO 级别刷大量
# 协议细节日志（如 httpx 的 receive_response_body/response_closed 生命周期事件、
# openai SDK 的请求/响应事件、asyncio 事件循环调度细节），经 InterceptHandler 桥接
# 进 loguru 后会淹没应用日志。统一提级 WARNING，只保留真正的告警/错误。
# 应用自身日志走 loguru 独立体系（由 setup_logging 的 sink level 控制，dev 仍可 DEBUG），
# 故此处降噪不影响应用可观测性。
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "openai",
    "openai._base_client",
    "asyncio",
    "urllib3",
    "urllib3.connectionpool",
    "charset_normalizer",
)


class InterceptHandler(logging.Handler):
    """标准库 logging -> loguru 桥接 handler。

    uvicorn / httpx 等第三方库默认走标准库 logging，与 loguru 输出割裂；用此 handler
    把它们的日志记录转发给 loguru，统一格式与目的地（loguru 官方推荐的桥接模式）。
    """

    def emit(self, record: logging.LogRecord) -> None:
        # 把标准库级别名映射到 loguru 级别；未知级别降级为数值级别
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # 回溯栈帧找到真正的日志发起者，让 loguru 显示正确的模块/函数/行号
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def intercept_uvicorn_logs(level: str = "INFO") -> None:
    """接管 uvicorn 三类日志，接入 loguru 统一输出。

    将 uvicorn / uvicorn.error / uvicorn.access 的 handler 替换为
    InterceptHandler，并关闭向上传播（propagate=False），避免重复打印。

    标准库根 logger 的级别是「拦截第三方库的门槛」，不应跟随应用 ``log_level``
    （后者走 loguru 独立体系）。传 DEBUG 会放行 httpx/openai 等第三方库的全部
    DEBUG 协议细节，故取「不低于 INFO」——既不丢失 uvicorn access/error（INFO+），
    又挡掉第三方库 DEBUG 噪音（与 ``_silence_noisy_loggers`` 双重保险）。
    """
    handler = InterceptHandler()
    root_level = max(getattr(logging, level.upper(), logging.INFO), logging.INFO)
    logging.basicConfig(handlers=[handler], level=root_level, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers = [handler]
        target.propagate = False


def _silence_noisy_loggers() -> None:
    """把第三方库噪音 logger 提级到 WARNING，避免协议细节淹没应用日志。

    httpx/openai 等出站 HTTP 客户端库的 DEBUG/INFO 日志是连接生命周期与协议细节，
    对排查业务无价值；经标准库 logging 派发、InterceptHandler 桥接进 loguru 后会刷屏。
    统一提级 WARNING，只保留真正的告警/错误（失败/重试/超时等）。排查 LLM 调用时若需
    临时查看 httpx 细节，可在调用处临时 ``logging.getLogger("httpx").setLevel("DEBUG")``，
    调试完即撤。
    """
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _build_patcher(app_cfg):
    """构造 patcher：给每条日志注入 env/service/request_id 三个上下文字段。

    三字段经 ``_DEFAULT_FORMAT`` 的 ``{extra[...]}`` 渲染进可读日志行，便于多环境/
    多服务区分与请求追踪；request_id 从请求上下文（ContextVar）读取，请求外为占位
    ``"-"``。延迟导入 ``get_request_id`` 以避免循环依赖（middleware/request_id 反向
    引用 logger）。
    """
    from app.middleware.request_id import get_request_id

    def _patcher(record):
        record["extra"].setdefault("env", app_cfg.env)
        record["extra"].setdefault("service", app_cfg.name)
        record["extra"]["request_id"] = get_request_id() or "-"

    return _patcher


def setup_logging(log_settings: LoggingSettings) -> list[int]:
    """按 LoggingSettings 配置生产级多 sink 日志。

    3 个 sink（全环境统一人类可读单行，enqueue=True 多进程安全）：
    - stdout：全量；
    - {dir}/app.log：全量，按 rotation/retention/compression 轮转；
    - {dir}/error.log：level≥ERROR 分流（告警/独立监控）。

    patcher 注入 env/service/request_id；diagnose/backtrace 按配置，生产
    diagnose=False 防敏感信息泄露。返回各 sink 的 handler id 列表，便于测试与运行期管理。
    """
    from app.core.config import get_settings

    app_cfg = get_settings().app
    level = log_settings.level.upper()

    logger.remove()
    logger.configure(patcher=_build_patcher(app_cfg))
    # 第三方库（httpx/openai 等）标准库 logging 噪音治理：与 loguru 应用日志级别解耦，
    # 在拦截器接管标准库 logging 之外，再对已知噪音库显式提级 WARNING（双保险）。
    _silence_noisy_loggers()

    log_dir = Path(log_settings.dir)
    log_dir.mkdir(parents=True, exist_ok=True)  # 确保日志目录存在

    file_kw = dict(  # 文件 sink 共享的轮转/保留/压缩
        rotation=log_settings.rotation,
        retention=log_settings.retention,
        compression=log_settings.compression,
    )
    common_kw = dict(  # 所有 sink 共享：统一可读格式
        level=level,
        format=_DEFAULT_FORMAT,
        backtrace=log_settings.backtrace,
        diagnose=log_settings.diagnose,
        enqueue=log_settings.enqueue,
    )
    return [
        logger.add(sys.stdout, **common_kw),
        logger.add(log_dir / "app.log", **file_kw, **common_kw),
        # error sink 覆盖 level 为 ERROR，其余沿用 common_kw
        logger.add(log_dir / "error.log", **file_kw, **{**common_kw, "level": "ERROR"}),
    ]
