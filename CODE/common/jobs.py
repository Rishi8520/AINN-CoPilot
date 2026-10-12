"""A bounded single-worker queue with atomic, persisted job snapshots."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import uuid


TERMINAL = {"completed", "failed", "cancelled"}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class JobConflict(Exception):
    pass


class QueueFull(Exception):
    pass


class JobQueue:
    def __init__(self, directory, handler, capacity=8):
        self.directory = Path(directory)
        self.handler = handler
        self.capacity = capacity
        self.lock = threading.RLock()
        self.records = {}
        self.cancellations = {}
        self.queue = None
        self.worker = None

    async def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            job_id = record["job_id"]
            self.records[job_id] = record
            if record["status"] not in TERMINAL:
                self.update(job_id, status="failed", stage="failed",
                            error="Service restarted before this job completed. Submit a new request.")
        self.queue = asyncio.Queue(maxsize=self.capacity)
        self.worker = asyncio.create_task(self._work())

    async def stop(self):
        for event in self.cancellations.values():
            event.set()
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        for job_id, record in list(self.records.items()):
            if record["status"] not in TERMINAL:
                self.update(job_id, status="cancelled", stage="cancelled", error="Service shutting down.")

    def _save(self, record):
        target = self.directory / f"{record['job_id']}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, allow_nan=False), encoding="utf-8")
        temporary.replace(target)

    def submit(self, request, request_id=None):
        if self.queue is None:
            raise QueueFull("Job service is not ready")
        with self.lock:
            if request_id:
                for record in self.records.values():
                    if record.get("request_id") == request_id:
                        if record["request"] != request:
                            raise JobConflict("request_id was already used with different inputs")
                        return self.get(record["job_id"])
            if sum(record["status"] not in TERMINAL for record in self.records.values()) >= self.capacity:
                raise QueueFull("Job queue is full. Retry after a running job finishes.")
            job_id = uuid.uuid4().hex
            record = {"job_id": job_id, "request_id": request_id, "request": request,
                      "status": "queued", "stage": "queued", "progress": 0.0,
                      "created_at": timestamp(), "updated_at": timestamp(),
                      "result": None, "error": None}
            self._save(record)
            self.records[job_id] = record
            self.cancellations[job_id] = threading.Event()
            self.queue.put_nowait(job_id)
            return self.get(job_id)

    def get(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise KeyError(job_id)
        with self.lock:
            if job_id not in self.records:
                raise KeyError(job_id)
            return deepcopy(self.records[job_id])

    def update(self, job_id, **fields):
        with self.lock:
            record = deepcopy(self.records[job_id])
            record.update(fields, updated_at=timestamp())
            self._save(record)
            self.records[job_id] = record

    def cancel(self, job_id):
        record = self.get(job_id)
        if record["status"] not in TERMINAL:
            self.cancellations[job_id].set()
            self.update(job_id, stage="cancelling")
        return self.get(job_id)

    async def _work(self):
        while True:
            job_id = await self.queue.get()
            event = self.cancellations[job_id]
            try:
                if event.is_set():
                    self.update(job_id, status="cancelled", stage="cancelled")
                    continue
                self.update(job_id, status="running", stage="preparing")
                result = await self.handler(self.get(job_id), event)
                if event.is_set():
                    self.update(job_id, status="cancelled", stage="cancelled")
                else:
                    self.update(job_id, status="completed", stage="completed", progress=1.0, result=result)
            except asyncio.CancelledError:
                event.set()
                raise
            except Exception as error:
                self.update(job_id, status="cancelled" if event.is_set() else "failed",
                            stage="cancelled" if event.is_set() else "failed", error=str(error))
            finally:
                self.cancellations.pop(job_id, None)
                self.queue.task_done()
