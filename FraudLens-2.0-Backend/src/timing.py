"""Opt-in, content-free stage timings for local performance diagnosis."""
from contextlib import contextmanager
import json
import logging
import os
import time
from functools import wraps


def measured(stage):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with span(stage):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def windows_memory():
    """Current process/host counters without adding an application dependency."""
    if os.name != 'nt':
        return {}
    import ctypes as c
    from ctypes import wintypes as w
    class Counters(c.Structure):
        _fields_ = [('cb', w.DWORD), ('faults', w.DWORD)] + [
            (name, c.c_size_t) for name in ('peak_working_set', 'working_set',
             'peak_paged_pool', 'paged_pool', 'peak_nonpaged_pool', 'nonpaged_pool',
             'pagefile', 'peak_pagefile')]
    class Memory(c.Structure):
        _fields_ = [('length', w.DWORD), ('load', w.DWORD)] + [
            (name, c.c_ulonglong) for name in ('total_physical', 'available_physical',
             'total_pagefile', 'available_pagefile', 'total_virtual', 'available_virtual', 'extended')]
    counters = Counters(); counters.cb = c.sizeof(counters)
    c.windll.kernel32.GetCurrentProcess.restype = w.HANDLE
    c.windll.psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.c_void_p, w.DWORD]
    if not c.windll.psapi.GetProcessMemoryInfo(c.windll.kernel32.GetCurrentProcess(), c.byref(counters), counters.cb):
        raise c.WinError()
    memory = Memory(); memory.length = c.sizeof(memory)
    if not c.windll.kernel32.GlobalMemoryStatusEx(c.byref(memory)):
        raise c.WinError()
    return {'rss_bytes': counters.working_set, 'peak_rss_bytes': counters.peak_working_set,
            'pagefile_bytes': counters.pagefile, 'physical_memory_bytes': memory.total_physical,
            'available_memory_bytes': memory.available_physical}

log = logging.getLogger('fraudlens.timing')


@contextmanager
def span(stage: str):
    if os.getenv('FRAUDLENS_PROFILE_STAGES') != '1':
        yield
        return
    started = time.perf_counter()
    cpu = time.process_time()
    failed = True
    try:
        yield
        failed = False
    finally:
        try:
            memory = windows_memory()
        except Exception:
            memory = {}  # Diagnostics must never change application behavior.
        log.info(json.dumps({'event': 'stage_timing', 'stage': stage,
            'elapsed_ms': round((time.perf_counter()-started)*1000, 3),
            'process_cpu_ms': round((time.process_time()-cpu)*1000, 3),
            'failed': failed, 'pid': os.getpid(), **memory}))
