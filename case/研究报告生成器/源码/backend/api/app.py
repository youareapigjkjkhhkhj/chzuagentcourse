from datetime import datetime, timezone
import mimetypes
from pathlib import Path
import threading
import traceback
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.analyst_agent import analyze
from agents.planner_agent import plan_task
from agents.rag_agent import build_rag_context
from agents.reader_agent import reader_agent
from agents.search_agent import search_agent
from agents.writer_agent import write_report
from tools.paper_sources import paper_source_label
from utils.file_utils import safe_filename, save_pdf, save_report


ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "generated_reports"

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")


class LLMConfig(BaseModel):
    provider: Literal["deepseek", "openai", "custom"] = "deepseek"
    api_key: str = Field("", max_length=300)
    model: str = Field("", max_length=120)
    base_url: str = Field("", max_length=300)


class ReportRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)
    max_results: int = Field(5, ge=1, le=10)
    years_back: int = Field(0, ge=0, le=20)
    paper_source: Literal[
        "arxiv",
        "semantic_scholar",
        "europe_pmc",
        "crossref",
        "all_open",
    ] = "arxiv"
    max_chars_per_paper: int = Field(5000, ge=1000, le=20000)
    top_k: int = Field(8, ge=1, le=20)
    language: Literal["auto", "zh", "en"] = "auto"
    use_rag: bool = True
    llm: LLMConfig | None = None


class JobStore:
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def create(self, request: ReportRequest):
        job_id = uuid4().hex
        now = _now()
        job = {
            "id": job_id,
            "topic": request.topic,
            "status": "queued",
            "stage": "Queued",
            "progress": 0,
            "created_at": now,
            "updated_at": now,
            "logs": [],
            "tasks": [],
            "papers": [],
            "evidence": [],
            "report": "",
            "files": {},
            "warnings": [],
            "error": None,
            "llm": _public_llm_config(request.llm),
            "search": {
                "years_back": request.years_back,
                "paper_source": request.paper_source,
                "source_label": paper_source_label(request.paper_source),
            },
        }
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self):
        with self._lock:
            return sorted(
                [dict(job) for job in self._jobs.values()],
                key=lambda item: item["created_at"],
                reverse=True,
            )

    def update(self, job_id, **updates):
        with self._lock:
            job = self._jobs[job_id]
            job.update(updates)
            job["updated_at"] = _now()
            return dict(job)

    def log(self, job_id, message):
        with self._lock:
            job = self._jobs[job_id]
            job["logs"].append({"time": _now(), "message": message})
            job["updated_at"] = _now()

    def warn(self, job_id, message):
        with self._lock:
            job = self._jobs[job_id]
            job["warnings"].append(message)
            job["logs"].append({"time": _now(), "message": f"Warning: {message}"})
            job["updated_at"] = _now()


def _now():
    return datetime.now(timezone.utc).isoformat()


jobs = JobStore()
app = FastAPI(title="研究报告生成器 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "time": _now()}


@app.post("/api/reports")
def create_report(request: ReportRequest):
    job = jobs.create(request)
    thread = threading.Thread(target=_run_report_job, args=(job["id"], request), daemon=True)
    thread.start()
    return {"report_id": job["id"], "job": job}


@app.get("/api/reports")
def list_reports():
    return {"jobs": jobs.list()}


@app.get("/api/reports/{job_id}")
def get_report(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found")
    return job


@app.get("/api/reports/{job_id}/download/{kind}")
def download_report(job_id: str, kind: Literal["markdown", "pdf"]):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found")

    path = job.get("files", {}).get(kind)
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail=f"{kind} file is not available")

    return FileResponse(path, filename=Path(path).name)


def _set_stage(job_id, stage, progress, status="running"):
    jobs.update(job_id, stage=stage, progress=progress, status=status)
    jobs.log(job_id, stage)


def _run_report_job(job_id: str, request: ReportRequest):
    try:
        output_dir = REPORT_ROOT / job_id
        filename_base = safe_filename(request.topic)

        _set_stage(job_id, "Planning research steps", 8)
        tasks = plan_task(request.topic)
        jobs.update(job_id, tasks=tasks)

        source_label = paper_source_label(request.paper_source)
        _set_stage(job_id, f"Searching {source_label} papers", 22)
        papers = search_agent(
            tasks,
            topic=request.topic,
            max_results=request.max_results,
            years_back=request.years_back,
            paper_source=request.paper_source,
            llm_config=request.llm,
        )
        jobs.update(job_id, papers=papers)
        if not papers:
            jobs.warn(job_id, f"No papers were found from {source_label} for this topic.")

        _set_stage(job_id, "Reading paper PDFs", 42)
        contents = reader_agent(papers, max_length=request.max_chars_per_paper)
        if not contents:
            jobs.warn(job_id, "No readable PDF content was extracted.")

        rag_context = ""
        evidence = []
        if request.use_rag and contents:
            _set_stage(job_id, "Building local RAG evidence", 58)
            rag_context, evidence = build_rag_context(
                request.topic,
                contents,
                top_k=request.top_k,
            )
            jobs.update(job_id, evidence=_slim_evidence(evidence))

        _set_stage(job_id, "Analyzing retrieved evidence", 72)
        summary = analyze(
            contents,
            topic=request.topic,
            rag_context=rag_context,
            llm_config=request.llm,
        )

        _set_stage(job_id, "Writing final report", 86)
        report = write_report(
            summary,
            request.topic,
            references=papers,
            rag_context=rag_context,
            language=request.language,
            llm_config=request.llm,
        )

        _set_stage(job_id, "Saving Markdown and PDF", 94)
        markdown_path = save_report(
            report,
            request.topic,
            output_dir=output_dir,
            filename_base=filename_base,
        )
        files = {"markdown": markdown_path}
        try:
            files["pdf"] = save_pdf(
                report,
                request.topic,
                output_dir=output_dir,
                filename_base=filename_base,
            )
        except Exception as exc:
            jobs.warn(job_id, f"PDF generation failed: {exc}")

        jobs.update(
            job_id,
            status="completed",
            stage="Completed",
            progress=100,
            report=report,
            files=files,
        )
        jobs.log(job_id, "Report completed")

    except Exception as exc:
        jobs.update(
            job_id,
            status="failed",
            stage="Failed",
            error=str(exc),
            progress=100,
        )
        jobs.log(job_id, traceback.format_exc())


def _slim_evidence(evidence):
    slim = []
    for item in evidence:
        slim.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "authors": item.get("authors"),
            "published": item.get("published"),
            "arxiv_url": item.get("arxiv_url"),
            "score": item.get("score"),
            "relevance": item.get("relevance"),
            "raw_vector_score": item.get("raw_vector_score"),
            "bm25_score": item.get("bm25_score"),
            "overlap_score": item.get("overlap_score"),
            "text": item.get("text", "")[:700],
        })
    return slim


def _public_llm_config(llm):
    if not llm:
        return {"provider": "deepseek", "model": "", "base_url": "", "has_api_key": False}
    return {
        "provider": llm.provider,
        "model": llm.model,
        "base_url": llm.base_url,
        "has_api_key": bool(llm.api_key),
    }


# 前端构建产物目录：源码/frontend/dist（与 backend 平级，镜像项目一/二约定）
frontend_dist = ROOT.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
