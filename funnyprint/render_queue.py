"""Priority render queue for chunk previews."""

import threading
import queue
import itertools


class RenderQueue:
    def __init__(self):
        self._pq = queue.PriorityQueue()
        self._seq = itertools.count()
        self._stop = False
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, priority, task_id, fn):
        """priority: lower number = higher priority"""
        self._pq.put((priority, next(self._seq), task_id, fn))

    def _run(self):
        while not self._stop:
            try:
                _priority, _seq, _task_id, fn = self._pq.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                fn()
            except Exception:
                # Ошибки пусть обрабатываются внутри fn / caller path
                pass
            finally:
                self._pq.task_done()

    def clear(self):
        """Грубая очистка очереди невыполненных задач."""
        while True:
            try:
                self._pq.get_nowait()
                self._pq.task_done()
            except queue.Empty:
                break

    def stop(self):
        self._stop = True
        self.clear()