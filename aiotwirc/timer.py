import time
import inspect


TIMES = {}


def spamming(seconds):
    '''
    >>> def f():
    ...     return spamming(0.01)
    >>> print(f(), f(), time.sleep(0.01), f())
    False True None False
    '''
    now = time.time()
    caller_frame = inspect.stack(2)[-1]
    caller = (caller_frame.filename, caller_frame.lineno)
    prev = TIMES.get(caller)
    if prev is None or prev + seconds < now:
        TIMES[caller] = now
        return False
    return True
