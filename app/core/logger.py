"""结构化日志（基于 loguru）。

提供全局 logger、setup_logging 与 intercept_uvicorn_logs：
- setup_logging：配 3 个 sink（stdout 全量 / app.log 全量 / error.log ERROR 分流）。
  按环境双模式：``serialize=False``（dev/test）输出人类可读单行（stdout 彩色、
  文件纯文本，颜色标签自动剥离）；``serialize=True``（prod）输出 JSON 供
  ELK/Loki 聚合。生产 diagnose=False 防异常栈泄露敏感变量。
- intercept_uvicorn_logs：把 uvicorn 标准库 logging 接入 loguru，使应用日志与
  uvicorn 访问/错误日志格式统一，便于生产排查。
"""
import json
import logging
import sys
import traceback
from pathlib import Path

from loguru import logger

from app.core.settings import LoggingSettings

# 默认日志格式：时间 | 级别 | 模块:函数:行号 [req_id=xxx] - 消息
# req_id 从 ContextVar 读取，若请求上下文外则为空（由 get_request_id 处理）
_DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>[req_id={extra[request_id]}]</level> | "
    "<level>{message}</level>"
)
# prod 精简 JSON：每行 = patcher 预生成的 {extra[__json__]}（serialize=False，弃用 loguru 全字段序列化）
_JSON_LINE_FORMAT = "{extra[__json__]}"


class InterceptHandler(logging.Handler):
    """标准库 logging -> loguru 桥接 handler。

    uvicorn 默认走标准库 logging，与 loguru 输出割裂；用此 handler 把
    uvicorn 的日志记录转发给 loguru，统一格式与目的地。
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
    """
    handler = InterceptHandler()
    logging.basicConfig(handlers=[handler], level=level.upper(), force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers = [handler]
        target.propagate = False


def _build_patcher(app_cfg):
    """构造 patcher：注入 env/service/request_id，并预生成精简 JSON 供 prod format 使用。

    dev/test 的可读 format 不引用 ``__json__``，多塞一个 extra 无害；prod 的
    format = ``{extra[__json__]}``，直接输出预生成的精简 JSON 行（仅
    time/level/logger/func/line/message/env/service/request_id + 异常时的 exception），
    杜绝 loguru serialize 全字段噪音（process/thread/elapsed/file 等）。
    """
    # 延迟导入避免循环依赖（middleware/request_id 导 logger，logger 反向导 get_request_id）
    from app.middleware.request_id import get_request_id

    def _patcher(record):
        record["extra"].setdefault("env", app_cfg.env)
        record["extra"].setdefault("service", app_cfg.name)
        # 尝试获取当前请求的 request_id（请求上下文外返回 None）
        request_id = get_request_id()
        record["extra"]["request_id"] = request_id if request_id else "-"
        payload = {
            "time": record["time"].isoformat(),
            "level": record["level"].name,
            "logger": record["name"],
            "func": record["function"],
            "line": record["line"],
            "message": record["message"],
            "env": record["extra"]["env"],
            "service": record["extra"]["service"],
            "request_id": record["extra"]["request_id"],
        }
        # prod format 不含 {message}，loguru 不会自动渲染异常栈，这里手动塞
        if record["exception"] is not None:
            exc = record["exception"]
            payload["exception"] = "".join(
                traceback.format_exception(exc.type, exc.value, exc.traceback)
            )
        record["extra"]["__json__"] = json.dumps(payload, ensure_ascii=False)

    return _patcher


def setup_logging(log_settings: LoggingSettings) -> list[int]:
    """按 LoggingSettings 配置生产级多 sink 日志。

    3 个 sink（均 serialize=JSON、enqueue=True）：
    - stdout：全量（容器/k8s 采集入口）；
    - {dir}/app.log：全量，按 rotation/retention/compression 轮转；
    - {dir}/error.log：level≥ERROR 分流（告警/独立监控）。

    经 patcher 注入 env/service 到每条日志 record.extra（JSON 序列化后落入 extra 字段）；
    diagnose/backtrace 按配置，生产 diagnose=False 防敏感信息泄露。返回各 sink 的
    handler id 列表，便于测试与运行期管理。
    """
    from app.core.config import get_settings

    app_cfg = get_settings().app
    level = log_settings.level.upper()

    logger.remove()
    logger.configure(patcher=_build_patcher(app_cfg))

    log_dir = Path(log_settings.dir)
    log_dir.mkdir(parents=True, exist_ok=True)  # 确保日志目录存在

    file_kw = dict(  # 文件 sink 共享的轮转/保留/压缩
        rotation=log_settings.rotation,
        retention=log_settings.retention,
        compression=log_settings.compression,
    )
    # serialize=True(prod)→精简 JSON 行；False(dev/test)→人类可读单行
    line_format = _JSON_LINE_FORMAT if log_settings.serialize else _DEFAULT_FORMAT
    common_kw = dict(  # 所有 sink 共享
        level=level,
        format=line_format,
        serialize=False,  # 不用 loguru 内置全字段序列化，改由 format+patcher 自管
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



