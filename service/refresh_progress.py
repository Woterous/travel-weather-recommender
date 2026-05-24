from __future__ import annotations

from queue import Empty, Queue
from threading import Lock
from uuid import uuid4


class RefreshJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Queue] = {}
        self._lock = Lock()

    def create(self) -> str:
        job_id = uuid4().hex
        with self._lock:
            self._jobs[job_id] = Queue()
        return job_id

    def emit(self, job_id: str, event: dict) -> None:
        with self._lock:
            queue = self._jobs.get(job_id)
        if queue is not None:
            queue.put(event)

    def listen(self, job_id: str, timeout: float = 15.0):
        with self._lock:
            queue = self._jobs.get(job_id)
        if queue is None:
            yield {"status": "error", "message": "刷新任务不存在或已结束。"}
            return

        while True:
            try:
                event = queue.get(timeout=timeout)
            except Empty:
                yield {"status": "heartbeat", "message": "刷新仍在进行，请稍候。"}
                continue

            yield event
            if event.get("status") in {"done", "warning", "error"}:
                with self._lock:
                    self._jobs.pop(job_id, None)
                return


refresh_jobs = RefreshJobStore()
