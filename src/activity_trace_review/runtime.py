"""POSIX wall-clock deadline in addition to cooperative core budget checks."""
from contextlib import contextmanager
import signal
from .core import Invalid, LIMITS

@contextmanager
def deadline(seconds=None):
    seconds = LIMITS['seconds'] if seconds is None else seconds
    if not hasattr(signal, 'setitimer'):
        raise Invalid('CLI/server require POSIX interval timers for processing deadlines')
    def expired(*_):
        raise Invalid('Processing time limit exceeded')
    handler = signal.signal(signal.SIGALRM, expired)
    previous = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous)
        signal.signal(signal.SIGALRM, handler)
