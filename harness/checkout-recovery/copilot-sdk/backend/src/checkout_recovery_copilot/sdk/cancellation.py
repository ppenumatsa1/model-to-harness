"""Explicit cross-thread cancellation, without changing business transactions."""

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar

_signal: ContextVar[threading.Event | None] = ContextVar("copilot_cancellation", default=None)
_disarm: ContextVar[Callable[[], None] | None] = ContextVar(
    "copilot_cancellation_disarm", default=None
)


@contextmanager
def cancellation_scope(signal: threading.Event) -> Iterator[None]:
    """Bind before scheduling asyncio.to_thread; set the signal to stop its worker."""
    token = _signal.set(signal)
    try:
        yield
    finally:
        _signal.reset(token)


def current_signal() -> threading.Event | None:
    return _signal.get()


def disarm_cancellation_watch() -> None:
    callback = _disarm.get()
    if callback is not None:
        callback()


@asynccontextmanager
async def watch_cancellation() -> AsyncIterator[None]:
    signal = current_signal()
    if signal is None:
        yield
        return
    if signal.is_set():
        raise asyncio.CancelledError("Copilot investigation cancelled")
    loop = asyncio.get_running_loop()
    owner = asyncio.current_task()
    timer = None
    stopped = False

    def stop() -> None:
        nonlocal stopped
        stopped = True
        if timer is not None:
            timer.cancel()

    def poll() -> None:
        nonlocal timer
        if stopped:
            return
        if signal.is_set():
            if owner is not None:
                owner.cancel("Copilot investigation cancelled")
            return
        timer = loop.call_later(0.05, poll)

    timer = loop.call_soon(poll)
    token = _disarm.set(stop)
    try:
        yield
    finally:
        stop()
        _disarm.reset(token)
