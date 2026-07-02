"""HTTP wrapper for SkillSpector CLI scans."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

SCANNER_VERSION = os.getenv("SKILLSPECTOR_VERSION", "2.1.4")
MAX_FILES = int(os.getenv("SKILLSPECTOR_SERVICE_MAX_FILES", "100"))
MAX_FILE_BYTES = int(os.getenv("SKILLSPECTOR_SERVICE_MAX_FILE_BYTES", str(1024 * 1024)))
MAX_TOTAL_BYTES = int(os.getenv("SKILLSPECTOR_SERVICE_MAX_TOTAL_BYTES", str(5 * 1024 * 1024)))

app = FastAPI(title="JoySafeter SkillSpector Service")


class ScanFile(BaseModel):
    path: str
    file_name: Optional[str] = None
    file_type: str = "text"
    content: str = ""

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError("path must be a safe relative path")
        return path.as_posix()


class ScanRequest(BaseModel):
    files: list[ScanFile] = Field(default_factory=list)
    no_llm: bool = True


def _write_files(scan_dir: Path, files: list[ScanFile]) -> None:
    if not files:
        raise HTTPException(status_code=400, detail="files is required")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail="too many files")

    total_bytes = 0
    for file in files:
        raw = file.content.encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail=f"file too large: {file.path}")
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=400, detail="total file content too large")
        target = scan_dir / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.content, encoding="utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "scanner": "skillspector", "scanner_version": SCANNER_VERSION}


@app.post("/scan")
def scan(req: ScanRequest) -> dict[str, Any]:
    temp_dir = Path(tempfile.mkdtemp(prefix="skillspector-"))
    report_file = temp_dir / "report.json"
    scan_dir = temp_dir / "skill"
    scan_dir.mkdir(parents=True, exist_ok=True)
    try:
        _write_files(scan_dir, req.files)
        cmd = ["skillspector", "scan", str(scan_dir), "--format", "json", "--output", str(report_file)]
        if req.no_llm:
            cmd.append("--no-llm")
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=float(os.getenv("SKILLSPECTOR_SERVICE_SCAN_TIMEOUT", "120")),
        )
        if not report_file.exists():
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "skillspector did not produce a JSON report",
                    "returncode": completed.returncode,
                    "stderr": completed.stderr[-4000:],
                },
            )
        report = json.loads(report_file.read_text(encoding="utf-8"))
        return {
            "scanner": "skillspector",
            "scanner_version": SCANNER_VERSION,
            "returncode": completed.returncode,
            "report": report,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
