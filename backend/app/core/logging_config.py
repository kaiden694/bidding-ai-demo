"""结构化 JSON 日志配置

功能：
- JSON 格式日志（便于 Loki 解析）
- 字段：timestamp/level/message/request_id/trace_id/span_id/module/line
- 日志级别：dev=DEBUG, prod=INFO
- 兼容现有 loguru 用法（from loguru import logger 仍可用）
- 兼容标准 logging 用法（logging.getLogger 仍可用，经 InterceptHandler 转发到 loguru）

设计要点：
- 以 loguru 作为统一日志引擎，保证现有代码无需修改
- 通过 InterceptHandler 将标准 logging 调用转发到 loguru，统一 JSON 输出
- request_id / trace_id / span_id 由 patcher 在调用线程读取 contextvars / OTel 上下文（async 安全）

使用：
- 在 app 启动时调用 setup_logging()
- 各模块仍用 from loguru import logger 或 logging.getLogger(__name__)
"""
import json
import logging
import sys
import traceback
from datetime import datetime, timezone

from loguru import logger

from app.core.config import settings


# 需要降低日志噪音的 logger
_NOISY_LOGGERS = ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore")


def _get_request_id() -> str:
    """从 contextvar 读取当前请求 ID（延迟导入避免循环依赖）"""
    try:
        from app.middleware.request_id import request_id_var

        return request_id_var.get() or ""
    except Exception:  # noqa: BLE001
        return ""


def _get_trace_context() -> tuple:
    """从 OpenTelemetry 上下文读取 trace_id / span_id（如已初始化）"""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and ctx.is_valid:
            return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
    except Exception:  # noqa: BLE001
        pass
    return "", ""


class JsonFormatter(logging.Formatter):
    """标准 logging 的 JSON 格式化器

    将 logging.LogRecord 格式化为单行 JSON，含 timestamp/level/message/
    module/line/request_id/trace_id/span_id 等字段，便于 Loki 解析。
    可独立用于标准 logging 的 Handler（如需要将标准 logging 直接输出为 JSON）。
    """

    def format(self, record: logging.LogRecord) -> str:
        request_id = _get_request_id()
        trace_id, span_id = _get_trace_context()

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
            "logger": record.name,
            "request_id": request_id,
            "trace_id": trace_id,
            "span_id": span_id,
        }

        # 额外字段（logger 额外传入的 user_id 等）
        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


class InterceptHandler(logging.Handler):
    """将标准 logging 调用转发到 loguru，统一日志管道

    这样 logging.getLogger(__name__) 的调用也会经过 loguru 的 JSON 输出，
    保证所有日志格式一致，避免多套格式给 Loki 解析带来负担。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except (ValueError, AttributeError):
            level = record.levelno

        # 找到真实的调用栈深度，保证 loguru 能正确显示调用位置
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _loguru_patcher(record) -> None:
    """loguru patcher：在日志生成时注入 request_id / trace_id / span_id

    patcher 在调用线程执行（loguru enqueue 之前），因此 contextvars 读取是安全的。
    """
    record["extra"]["request_id"] = _get_request_id()
    trace_id, span_id = _get_trace_context()
    record["extra"]["trace_id"] = trace_id
    record["extra"]["span_id"] = span_id


def _build_log_entry(message) -> str:
    """将 loguru 消息序列化为单行 JSON（扁平字段，便于 Loki 解析）"""
    record = message.record
    extra = record["extra"]

    # 时间戳：ISO8601 含毫秒 + Z 后缀
    time = record["time"]
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.") + f"{time.microsecond // 1000:03d}Z"

    entry = {
        "timestamp": timestamp,
        "level": record["level"].name,
        "message": record["message"],
        "module": record["name"],
        "line": record["line"],
        "request_id": extra.get("request_id", ""),
        "trace_id": extra.get("trace_id", ""),
        "span_id": extra.get("span_id", ""),
    }

    if record.get("exception"):
        exc = record["exception"]
        entry["exception"] = "".join(
            traceback.format_exception(exc.type, exc.value, exc.traceback)
        )

    return json.dumps(entry, ensure_ascii=False)


def _json_stdout_sink(message) -> None:
    """loguru sink：向 stdout 输出单行 JSON（docker logs / Promtail 采集）"""
    sys.stdout.write(_build_log_entry(message) + "\n")
    sys.stdout.flush()


def setup_logging(log_level: str = None) -> None:
    """配置全局日志（在 app 启动时调用）

    - 重配置 loguru：stdout（自定义扁平 JSON）+ 文件（loguru 序列化 JSON，按日轮转）
    - 标准 logging：InterceptHandler 转发到 loguru（统一管道）
    - 降低 uvicorn / sqlalchemy / httpx 噪音日志到 WARNING
    """
    level = log_level or settings.APP_LOG_LEVEL

    # 1. 重置 loguru：移除默认 handler，挂载 patcher 注入上下文字段
    logger.remove()
    logger.configure(patcher=_loguru_patcher)

    # 2. loguru JSON sink → stdout（扁平 JSON，Promtail 主要采集源）
    logger.add(
        _json_stdout_sink,
        level=level,
        backtrace=True,
        diagnose=settings.APP_ENV == "dev",
        enqueue=True,
        catch=True,
    )

    # 3. loguru JSON sink → 按日轮转文件（保留 30 天，zip 压缩，本地备份）
    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        level=level,
        backtrace=True,
        diagnose=False,
        enqueue=True,
        catch=True,
        rotation="00:00",
        retention="30 days",
        compression="zip",
        serialize=True,  # loguru 内置 JSON 序列化（含 extra 字段，保证单行可解析）
    )

    # 4. 标准 logging → InterceptHandler → loguru（统一管道，避免格式分裂）
    logging.basicConfig(handlers=[InterceptHandler()], level=level, force=True)

    # 5. 降低噪音日志级别到 WARNING
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
