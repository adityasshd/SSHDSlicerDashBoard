"""Conservative thread use for shared hosting and report reads."""
import os
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock


def configure_numeric_threads():
    """Set defaults before NumPy or libraries importing it initialize BLAS."""
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS',
                 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ.setdefault(name, '1')


class ReadExecutor:
    """Bound parallel reads and run inline when the host cannot start a thread.

    Each submitted call owns its result Future. A failed thread start can leave
    the call queued in the underlying executor, so guard execution to prevent
    that queued copy from repeating a call already completed inline.
    """
    def __init__(self, max_workers):
        if max_workers < 1:
            raise ValueError('max_workers must be positive')
        try:
            limit = max(1, int(os.getenv('DASHBOARD_MAX_WORKERS', '2')))
        except ValueError:
            limit = 2
        workers = min(max_workers, limit)
        self._pool = ThreadPoolExecutor(max_workers=workers) if limit > 1 else None
        self._inline = self._pool is None

    def submit(self, function, /, *args, **kwargs):
        future = Future()
        execution_lock = Lock()
        started = False

        def run():
            nonlocal started
            with execution_lock:
                if started:
                    return
                started = True
                if not future.set_running_or_notify_cancel():
                    return
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                future.set_exception(error)
            else:
                future.set_result(result)

        if self._inline:
            run()
        else:
            try:
                self._pool.submit(run)
            except RuntimeError as error:
                if "can't start new thread" not in str(error):
                    raise
                self._inline = True
                run()
        return future

    def map(self, function, *iterables):
        futures = [self.submit(function, *args) for args in zip(*iterables)]
        return (future.result() for future in futures)

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        if self._pool is not None:
            self._pool.shutdown(wait=True)
