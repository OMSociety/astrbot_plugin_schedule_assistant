"""
错误处理模块

提供错误处理装饰器、重试机制和错误日志增强功能。
"""

import asyncio
import functools
import time
import traceback
from collections.abc import Callable
from typing import Any, TypeVar

from astrbot.api import logger

from .constants import LOG_PREFIX

F = TypeVar("F", bound=Callable[..., Any])


def with_error_handling(
    log_prefix: str = LOG_PREFIX, reraise: bool = True, default_return: Any = None
) -> Callable[[F], F]:
    """错误处理装饰器

    Args:
        log_prefix: 日志前缀
        reraise: 是否重新抛出异常
        default_return: 异常时的默认返回值
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # 获取详细的错误信息
                error_type = type(e).__name__
                error_msg = str(e)
                error_traceback = traceback.format_exc()

                # 提取调用信息
                func_name = func.__name__
                module_name = func.__module__

                # 记录详细错误日志
                logger.error(
                    f"{log_prefix} {module_name}.{func_name} 执行失败\n"
                    f"错误类型: {error_type}\n"
                    f"错误信息: {error_msg}\n"
                    f"堆栈跟踪:\n{error_traceback}"
                )

                if reraise:
                    raise
                return default_return

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 获取详细的错误信息
                error_type = type(e).__name__
                error_msg = str(e)
                error_traceback = traceback.format_exc()

                # 提取调用信息
                func_name = func.__name__
                module_name = func.__module__

                # 记录详细错误日志
                logger.error(
                    f"{log_prefix} {module_name}.{func_name} 执行失败\n"
                    f"错误类型: {error_type}\n"
                    f"错误信息: {error_msg}\n"
                    f"堆栈跟踪:\n{error_traceback}"
                )

                if reraise:
                    raise
                return default_return

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def with_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
    log_prefix: str = LOG_PREFIX,
) -> Callable[[F], F]:
    """重试装饰器

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff_factor: 退避因子
        exceptions: 需要重试的异常类型
        log_prefix: 日志前缀
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{log_prefix} {func.__name__} 第 {attempt + 1} 次尝试失败，"
                            f"{current_delay:.1f}秒后重试: {e}"
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.error(
                            f"{log_prefix} {func.__name__} 达到最大重试次数 ({max_retries})，"
                            f"最后一次错误: {e}"
                        )

            raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{log_prefix} {func.__name__} 第 {attempt + 1} 次尝试失败，"
                            f"{current_delay:.1f}秒后重试: {e}"
                        )
                        import time

                        time.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.error(
                            f"{log_prefix} {func.__name__} 达到最大重试次数 ({max_retries})，"
                            f"最后一次错误: {e}"
                        )

            raise last_exception

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class CircuitBreaker:
    """断路器模式实现"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self._failure_count = 0
        self._last_failure_time = 0
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def can_execute(self) -> bool:
        """检查是否可以执行"""
        if self._state == "CLOSED":
            return True
        elif self._state == "OPEN":
            # 检查是否到了恢复时间
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = "HALF_OPEN"
                return True
            return False
        else:  # HALF_OPEN
            return True

    def record_success(self):
        """记录成功"""
        self._failure_count = 0
        self._state = "CLOSED"

    def record_failure(self):
        """记录失败"""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._failure_count >= self.failure_threshold:
            self._state = "OPEN"
            logger.warning(f"{LOG_PREFIX} 断路器打开，失败次数: {self._failure_count}")

    def get_state(self) -> str:
        """获取断路器状态"""
        return self._state


def with_circuit_breaker(
    circuit_breaker: CircuitBreaker,
    fallback_return: Any = None,
    log_prefix: str = LOG_PREFIX,
) -> Callable[[F], F]:
    """断路器装饰器

    Args:
        circuit_breaker: 断路器实例
        fallback_return: 断路器打开时的默认返回值
        log_prefix: 日志前缀
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not circuit_breaker.can_execute():
                logger.warning(f"{log_prefix} {func.__name__} 断路器打开，使用降级方案")
                return fallback_return

            try:
                result = await func(*args, **kwargs)
                circuit_breaker.record_success()
                return result
            except circuit_breaker.expected_exception:
                circuit_breaker.record_failure()
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not circuit_breaker.can_execute():
                logger.warning(f"{log_prefix} {func.__name__} 断路器打开，使用降级方案")
                return fallback_return

            try:
                result = func(*args, **kwargs)
                circuit_breaker.record_success()
                return result
            except circuit_breaker.expected_exception:
                circuit_breaker.record_failure()
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
