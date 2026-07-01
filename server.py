"""FastAPI front-end for the recap solver.

Endpoints:
  POST /solve            synchronous solve, returns the token
  POST /jobs             enqueue an async solve, returns a job id
  GET  /jobs/{id}        poll job state
  DELETE /jobs/{id}      drop a finished job
"""
from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from recap import Recaptcha

MAX_CONCURRENCY = 5
DEFAULT_TIMEOUT = 30.0
# Cap retained jobs so a client that never calls DELETE can't grow app.state.jobs
# without bound. Finished jobs are evicted oldest-first once over the cap.
MAX_JOB_CACHE = 1000


class SolveRequest(BaseModel):
    url: str
    sitekey: str
    action: str = "submit"
    enterprise: bool = False
    proxy: Optional[str] = None
    headless: bool = True
    timeout: Optional[float] = None


class SolveResult(BaseModel):
    success: bool
    token: Optional[str] = None
    error: Optional[str] = None
    elapsed: float


class JobCreated(BaseModel):
    job_id: str


class JobStatus(BaseModel):
    job_id: str
    state: str
    token: Optional[str] = None
    error: Optional[str] = None
    elapsed: Optional[float] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sem = asyncio.Semaphore(MAX_CONCURRENCY)
    app.state.jobs = {}
    yield
    app.state.jobs.clear()


app = FastAPI(title="recap", version="2.0.0", lifespan=lifespan)


def _evict_finished_jobs(jobs: dict) -> None:
    """Drop the oldest finished jobs once the store exceeds MAX_JOB_CACHE.

    Running/pending jobs are never evicted; dict insertion order gives oldest
    first. This bounds memory for callers that never DELETE their jobs.
    """
    overflow = len(jobs) - MAX_JOB_CACHE
    if overflow < 0:
        return
    for job_id in list(jobs):
        if overflow < 0:
            break
        if jobs[job_id].state in ("done", "error"):
            del jobs[job_id]
            overflow -= 1



async def _run(req: SolveRequest) -> SolveResult:
    start = time.monotonic()
    timeout = req.timeout or DEFAULT_TIMEOUT
    solver = Recaptcha(proxy=req.proxy, headless=req.headless)
    try:
        async with app.state.sem:
            token = await asyncio.wait_for(
                solver.asolve(req.url, req.sitekey, req.action, req.enterprise),
                timeout=timeout,
            )
        return SolveResult(success=True, token=token,
                           elapsed=round(time.monotonic() - start, 2))
    except asyncio.TimeoutError:
        return SolveResult(success=False, error=f"Timed out after {timeout}s",
                           elapsed=round(time.monotonic() - start, 2))
    except Exception as exc:  # surface solver failures to the caller
        return SolveResult(success=False, error=str(exc),
                           elapsed=round(time.monotonic() - start, 2))


@app.post("/solve", response_model=SolveResult)
async def solve(req: SolveRequest):
    return await _run(req)


@app.post("/jobs", response_model=JobCreated)
async def create_job(req: SolveRequest):
    job_id = uuid.uuid4().hex
    _evict_finished_jobs(app.state.jobs)
    app.state.jobs[job_id] = JobStatus(job_id=job_id, state="pending")

    async def worker():
        app.state.jobs[job_id].state = "running"
        result = await _run(req)
        app.state.jobs[job_id] = JobStatus(
            job_id=job_id,
            state="done" if result.success else "error",
            token=result.token,
            error=result.error,
            elapsed=result.elapsed,
        )

    asyncio.create_task(worker())
    return JobCreated(job_id=job_id)


@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str):
    job = app.state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    app.state.jobs.pop(job_id, None)
    return {"deleted": job_id}


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8778, log_level="info")
