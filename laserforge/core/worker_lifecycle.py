"""
LaserForge Worker Lifecycle Manager.
Provides centralized registration, monitoring, and graceful shutdown
for all background worker threads in the application.
"""

import threading
import time
import warnings
from typing import Optional, List, Callable, Dict


class ManagedWorker:
    """
    Wraps a background thread with lifecycle management and a stop signal.
    Register with WorkerLifecycleManager for coordinated application shutdown.
    """
    def __init__(self, name: str, thread: threading.Thread, stop_fn: Optional[Callable] = None):
        self.name = name
        self.thread = thread
        self._stop_fn = stop_fn
        self.stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        """True if the worker thread is currently alive."""
        return self.thread.is_alive()

    def stop(self, timeout: float = 5.0) -> bool:
        """Signals the worker to stop and waits up to timeout seconds. Returns True if stopped cleanly."""
        self.stop_event.set()
        if self._stop_fn:
            try:
                self._stop_fn()
            except Exception:
                pass
        self.thread.join(timeout=timeout)
        return not self.thread.is_alive()


class WorkerLifecycleManager:
    """
    Singleton manager for all LaserForge background worker threads.
    Ensures graceful coordinated shutdown of all workers when the application exits.
    Call shutdown_all() from main() before sys.exit().
    """
    _instance: Optional['WorkerLifecycleManager'] = None
    _class_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> 'WorkerLifecycleManager':
        with cls._class_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._workers: Dict[str, ManagedWorker] = {}
                inst._lock = threading.Lock()
                cls._instance = inst
        return cls._instance

    def register(self, name: str, thread: threading.Thread,
                 stop_fn: Optional[Callable] = None) -> ManagedWorker:
        """Register a background thread for lifecycle management."""
        worker = ManagedWorker(name, thread, stop_fn)
        with self._lock:
            self._workers[name] = worker
        return worker

    def unregister(self, name: str) -> None:
        """Remove a worker from lifecycle management (e.g., after it finishes naturally)."""
        with self._lock:
            self._workers.pop(name, None)

    def get_worker(self, name: str) -> Optional[ManagedWorker]:
        """Returns the ManagedWorker with the given name, or None."""
        with self._lock:
            return self._workers.get(name)

    def list_running(self) -> List[str]:
        """Returns the names of all currently alive worker threads."""
        with self._lock:
            return [name for name, w in self._workers.items() if w.is_running]

    def shutdown_all(self, timeout: float = 5.0) -> Dict[str, bool]:
        """
        Gracefully stops all registered background workers.
        Returns a dict mapping worker name -> True (stopped cleanly) or False (timed out).
        """
        with self._lock:
            snapshot = dict(self._workers)
        results: Dict[str, bool] = {}
        for name, worker in snapshot.items():
            if worker.is_running:
                stopped = worker.stop(timeout=timeout)
                results[name] = stopped
                if not stopped:
                    warnings.warn(
                        f'[LaserForge] Worker {name!r} did not stop within {timeout}s',
                        RuntimeWarning,
                        stacklevel=2
                    )
            else:
                results[name] = True
        with self._lock:
            self._workers.clear()
        return results


def get_lifecycle_manager() -> WorkerLifecycleManager:
    """Returns the global WorkerLifecycleManager singleton."""
    return WorkerLifecycleManager()
