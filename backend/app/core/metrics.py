"""
指标收集器（线程安全的内存计数器）

设计要点：
- 单例模式（双重检查锁定，线程安全）
- threading.Lock 保护所有写入操作
- 延迟采样：HTTP/LLM 延迟仅保留最近 N 个样本，避免内存无限增长
- 手动构建 Prometheus 文本格式（不引入 prometheus_client 库，避免额外依赖）

指标命名遵循 Prometheus 约定：
- _total 后缀：计数器（单调递增）
- _seconds 后缀：直方图/延迟
- 标签：method/path/status/provider 等低基数维度
"""
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional


# 延迟样本上限（超出后裁剪保留最近一半）
_HTTP_DURATION_MAX_SAMPLES = 1000
_LLM_DURATION_MAX_SAMPLES = 500


class MetricsCollector:
    """线程安全的指标收集器（单例）"""

    _instance: Optional["MetricsCollector"] = None
    _lock = threading.Lock()

    def __init__(self):
        # HTTP 指标
        # key=(method, path, status) -> count（计数器，单调递增）
        self._http_requests: dict[tuple, int] = defaultdict(int)
        # key=(method, path) -> [durations]（延迟样本，环形裁剪）
        self._http_duration: dict[tuple, list] = defaultdict(list)

        # LLM 指标
        # key=(provider, model, success) -> count
        self._llm_requests: dict[tuple, int] = defaultdict(int)
        # key=provider -> [durations]
        self._llm_duration: dict[str, list] = defaultdict(list)

        # Celery 指标
        # key=(task, status) -> count
        self._celery_tasks: dict[tuple, int] = defaultdict(int)
        # key=task -> [durations]
        self._celery_duration: dict[str, list] = defaultdict(list)

        # 启动时间（用于 uptime 指标）
        self._started_at = datetime.now(timezone.utc)

    # ============================================================
    # 单例（双重检查锁定）
    # ============================================================
    @classmethod
    def get_instance(cls) -> "MetricsCollector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ============================================================
    # HTTP 指标记录
    # ============================================================
    def record_http_request(self, method: str, path: str, status: int, duration: float) -> None:
        """记录一次 HTTP 请求

        - method: HTTP 方法（GET/POST/...）
        - path: 归一化后的路径（UUID 已替换为 {id}）
        - status: HTTP 状态码
        - duration: 耗时（秒，浮点）
        """
        with self._lock:
            self._http_requests[(method, path, status)] += 1
            samples = self._http_duration[(method, path)]
            samples.append(duration)
            if len(samples) > _HTTP_DURATION_MAX_SAMPLES:
                # 保留最近一半，避免反复裁剪
                del samples[: len(samples) - _HTTP_DURATION_MAX_SAMPLES // 2]

    # ============================================================
    # LLM 指标记录
    # ============================================================
    def record_llm_request(
        self, provider: str, model: str, success: bool, duration: float
    ) -> None:
        """记录一次 LLM 调用

        - provider: 提供商名称
        - model: 模型名
        - success: 是否成功
        - duration: 耗时（秒）
        """
        with self._lock:
            self._llm_requests[(provider, model, "true" if success else "false")] += 1
            samples = self._llm_duration[provider]
            samples.append(duration)
            if len(samples) > _LLM_DURATION_MAX_SAMPLES:
                del samples[: len(samples) - _LLM_DURATION_MAX_SAMPLES // 2]

    # ============================================================
    # Celery 指标记录
    # ============================================================
    def record_celery_task(self, task: str, status: str, duration: float) -> None:
        """记录一次 Celery 任务执行

        - task: 任务名
        - status: success / failure / retry
        - duration: 耗时（秒）
        """
        with self._lock:
            self._celery_tasks[(task, status)] += 1
            samples = self._celery_duration[task]
            samples.append(duration)
            if len(samples) > _LLM_DURATION_MAX_SAMPLES:
                del samples[: len(samples) - _LLM_DURATION_MAX_SAMPLES // 2]

    # ============================================================
    # 快照读取（在锁内拷贝，避免格式化期间数据变化）
    # ============================================================
    def _snapshot(self) -> dict:
        with self._lock:
            return {
                "http_requests": dict(self._http_requests),
                "http_duration": {k: list(v) for k, v in self._http_duration.items()},
                "llm_requests": dict(self._llm_requests),
                "llm_duration": {k: list(v) for k, v in self._llm_duration.items()},
                "celery_tasks": dict(self._celery_tasks),
                "celery_duration": {k: list(v) for k, v in self._celery_duration.items()},
                "started_at": self._started_at,
            }

    # ============================================================
    # 辅助：分位数计算
    # ============================================================
    @staticmethod
    def _quantile(sorted_samples: list, q: float) -> float:
        """计算分位数（输入需已排序）"""
        if not sorted_samples:
            return 0.0
        if q <= 0:
            return sorted_samples[0]
        if q >= 1:
            return sorted_samples[-1]
        # 线性插值
        idx = (len(sorted_samples) - 1) * q
        lo = int(idx)
        hi = min(lo + 1, len(sorted_samples) - 1)
        frac = idx - lo
        return sorted_samples[lo] + (sorted_samples[hi] - sorted_samples[lo]) * frac

    # ============================================================
    # Prometheus 文本格式输出
    # ============================================================
    def format_prometheus(self) -> str:
        """构建 Prometheus 文本格式输出

        格式参考：
        # HELP metric_name 帮助文本
        # TYPE metric_name counter|gauge|histogram|summary
        metric_name{label="value"} 123 1700000000000
        """
        snap = self._snapshot()
        lines: list[str] = []

        # ---------------- HTTP 请求总数 ----------------
        lines.append("# HELP http_requests_total HTTP 请求总数（按 method/path/status 分组）")
        lines.append("# TYPE http_requests_total counter")
        for (method, path, status), count in sorted(snap["http_requests"].items()):
            lines.append(
                f'http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
            )

        # ---------------- HTTP 延迟（summary：count + sum + 分位数）----------------
        # 用 summary 类型而非 histogram，避免定义 bucket 边界
        lines.append("# HELP http_request_duration_seconds HTTP 请求延迟（秒）")
        lines.append("# TYPE http_request_duration_seconds summary")
        for (method, path), samples in sorted(snap["http_duration"].items()):
            if not samples:
                continue
            sorted_s = sorted(samples)
            count = len(sorted_s)
            total = sum(sorted_s)
            labels = f'method="{method}",path="{path}"'
            lines.append(f'http_request_duration_seconds{{{labels},quantile="0.5"}} {self._quantile(sorted_s, 0.5):.6f}')
            lines.append(f'http_request_duration_seconds{{{labels},quantile="0.9"}} {self._quantile(sorted_s, 0.9):.6f}')
            lines.append(f'http_request_duration_seconds{{{labels},quantile="0.95"}} {self._quantile(sorted_s, 0.95):.6f}')
            lines.append(f'http_request_duration_seconds{{{labels},quantile="0.99"}} {self._quantile(sorted_s, 0.99):.6f}')
            lines.append(f'http_request_duration_seconds_count{{{labels}}} {count}')
            lines.append(f'http_request_duration_seconds_sum{{{labels}}} {total:.6f}')

        # ---------------- LLM 请求总数 ----------------
        lines.append("# HELP llm_requests_total LLM 请求总数（按 provider/model/success 分组）")
        lines.append("# TYPE llm_requests_total counter")
        for (provider, model, success), count in sorted(snap["llm_requests"].items()):
            lines.append(
                f'llm_requests_total{{provider="{provider}",model="{model}",success="{success}"}} {count}'
            )

        # ---------------- LLM 延迟 ----------------
        lines.append("# HELP llm_latency_seconds LLM 调用延迟（秒）")
        lines.append("# TYPE llm_latency_seconds summary")
        for provider, samples in sorted(snap["llm_duration"].items()):
            if not samples:
                continue
            sorted_s = sorted(samples)
            count = len(sorted_s)
            total = sum(sorted_s)
            labels = f'provider="{provider}"'
            lines.append(f'llm_latency_seconds{{{labels},quantile="0.5"}} {self._quantile(sorted_s, 0.5):.6f}')
            lines.append(f'llm_latency_seconds{{{labels},quantile="0.95"}} {self._quantile(sorted_s, 0.95):.6f}')
            lines.append(f'llm_latency_seconds{{{labels},quantile="0.99"}} {self._quantile(sorted_s, 0.99):.6f}')
            lines.append(f'llm_latency_seconds_count{{{labels}}} {count}')
            lines.append(f'llm_latency_seconds_sum{{{labels}}} {total:.6f}')

        # ---------------- Celery 任务总数 ----------------
        lines.append("# HELP celery_tasks_total Celery 任务执行总数（按 task/status 分组）")
        lines.append("# TYPE celery_tasks_total counter")
        for (task, status), count in sorted(snap["celery_tasks"].items()):
            lines.append(
                f'celery_tasks_total{{task="{task}",status="{status}"}} {count}'
            )

        # ---------------- Celery 任务耗时 ----------------
        lines.append("# HELP celery_task_duration_seconds Celery 任务执行耗时（秒）")
        lines.append("# TYPE celery_task_duration_seconds summary")
        for task, samples in sorted(snap["celery_duration"].items()):
            if not samples:
                continue
            sorted_s = sorted(samples)
            count = len(sorted_s)
            total = sum(sorted_s)
            labels = f'task="{task}"'
            lines.append(f'celery_task_duration_seconds{{{labels},quantile="0.5"}} {self._quantile(sorted_s, 0.5):.6f}')
            lines.append(f'celery_task_duration_seconds{{{labels},quantile="0.95"}} {self._quantile(sorted_s, 0.95):.6f}')
            lines.append(f'celery_task_duration_seconds_count{{{labels}}} {count}')
            lines.append(f'celery_task_duration_seconds_sum{{{labels}}} {total:.6f}')

        # ---------------- 进程运行时长 ----------------
        lines.append("# HELP process_uptime_seconds 进程运行时长（秒）")
        lines.append("# TYPE process_uptime_seconds gauge")
        uptime = (datetime.now(timezone.utc) - snap["started_at"]).total_seconds()
        lines.append(f"process_uptime_seconds {uptime:.2f}")

        return "\n".join(lines) + "\n"


# 全局访问函数
def get_metrics_collector() -> MetricsCollector:
    """获取指标收集器单例"""
    return MetricsCollector.get_instance()
