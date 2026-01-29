"""
Scan routes for whitebox scanning feature
"""

import io
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from loguru import logger

from app.dynamic_agent.core.scanner.manager import ScannerManager
from app.dynamic_agent.models.scan import ScanJobResponse, ScanJobStatus, ScanStatus

router = APIRouter(prefix="/scan", tags=["scan"])

# In-memory storage for scan jobs
# In production, this should be Redis or a database
SCAN_JOBS = {}


@router.post(
    "/upload",
    response_model=ScanJobResponse,
    summary="Upload ZIP and start scan",
    status_code=202,
)
async def upload_and_scan(
    file: UploadFile = File(...),
    max_file_size: int = Query(10 * 1024 * 1024, description="Maximum file size in bytes (default: 10MB)"),
):
    """
    Upload a ZIP file and start an async vulnerability scan.

    Args:
        file: ZIP file containing source code
        max_file_size: Maximum allowed file size in bytes

    Returns:
        ScanJobResponse with job ID and initial status

    Raises:
        HTTPException: If file is invalid or too large
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".zip"):
        logger.error(f"Invalid file type: {file.filename}")
        raise HTTPException(status_code=400, detail="File must be a ZIP archive")

    # Check file size
    # Read first chunk to check size
    await file.read(1024)
    await file.seek(0)

    # For simplicity, we'll check size after reading the entire file
    # In production, consider streaming with size validation
    contents = await file.read()

    if len(contents) > max_file_size:
        logger.error(f"File too large: {len(contents)} bytes (max: {max_file_size})")
        raise HTTPException(
            status_code=400, detail=f"File too large. Maximum size is {max_file_size / (1024 * 1024):.1f}MB"
        )

    # Validate ZIP file
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as zf:
            # Try to read the file list to validate the ZIP
            _ = zf.namelist()
    except zipfile.BadZipFile as e:
        logger.error(f"Invalid ZIP file: {e}")
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    # Create scan job
    job_id = uuid4()
    SCAN_JOBS[job_id] = {
        "status": ScanStatus.QUEUED,
        "progress": 0,
        "created_at": datetime.now().isoformat(),
        "file_path": None,
        "error": None,
        "result": None,
    }

    # Save file to temp location
    temp_dir = tempfile.mkdtemp(prefix="scan_upload_")
    temp_path = os.path.join(temp_dir, f"{job_id}.zip")

    try:
        with open(temp_path, "wb") as f:
            f.write(contents)

        SCAN_JOBS[job_id]["file_path"] = temp_path

        # Start scan in background
        # In production, this should be Celery or similar
        import asyncio

        asyncio.create_task(run_scan_async(job_id, temp_path))

        logger.info(f"✓ Started scan job {job_id} for file {file.filename}")

        return ScanJobResponse(job_id=job_id, status=ScanStatus.QUEUED, message=f"Scan started for {file.filename}")

    except Exception as e:
        logger.error(f"Failed to start scan: {e}")
        # Cleanup
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to start scan: {str(e)}")


@router.get(
    "/status/{job_id}",
    response_model=ScanJobStatus,
    summary="Get scan status and results",
)
async def get_scan_status(job_id: UUID):
    """
    Get the status of a scan job and its results if completed.

    Args:
        job_id: The scan job ID

    Returns:
        ScanJobStatus with current progress and results if complete

    Raises:
        HTTPException: If job not found
    """
    if job_id not in SCAN_JOBS:
        logger.error(f"Job not found: {job_id}")
        raise HTTPException(status_code=404, detail="Scan job not found")

    job = SCAN_JOBS[job_id]

    # Build response
    progress_val = job.get("progress", 0)
    # Convert to int safely
    if isinstance(progress_val, (int, float)):
        progress_int = int(progress_val)
    else:
        progress_int = 0

    response = ScanJobStatus(
        job_id=job_id,
        status=ScanStatus(job["status"]),
        progress=progress_int,
    )

    # Add error if failed
    if job["status"] == ScanStatus.FAILED and job.get("error"):
        error_val = job["error"]
        response.error = str(error_val) if error_val is not None else None

    # Add result if completed
    if job["status"] == ScanStatus.COMPLETED and job.get("result"):
        result_val = job["result"]
        # result is Optional[ScanReport], keep as is if it's already the right type
        response.result = result_val  # type: ignore[assignment]

    return response


async def run_scan_async(job_id: UUID, zip_path: str):
    """
    Run scan asynchronously.

    Args:
        job_id: The scan job ID
        zip_path: Path to the ZIP file
    """
    try:
        logger.info(f"Scan {job_id}: Starting")
        SCAN_JOBS[job_id]["status"] = ScanStatus.PROCESSING
        SCAN_JOBS[job_id]["progress"] = 10

        # Initialize scanner
        scanner = ScannerManager()
        SCAN_JOBS[job_id]["progress"] = 20

        # Run scan
        logger.info(f"Scan {job_id}: Running scanner...")
        result = scanner.run_scan(zip_path)

        # Update progress
        SCAN_JOBS[job_id]["progress"] = 90

        # Store result
        SCAN_JOBS[job_id]["result"] = result
        SCAN_JOBS[job_id]["status"] = ScanStatus.COMPLETED
        SCAN_JOBS[job_id]["progress"] = 100

        logger.info(f"Scan {job_id}: Completed with {result['summary']['total']} findings")

    except zipfile.BadZipFile as e:
        logger.error(f"Scan {job_id}: Invalid ZIP file - {e}")
        SCAN_JOBS[job_id]["status"] = ScanStatus.FAILED
        SCAN_JOBS[job_id]["error"] = f"Invalid ZIP file: {str(e)}"

    except Exception as e:
        logger.error(f"Scan {job_id}: Failed - {e}", exc_info=True)
        SCAN_JOBS[job_id]["status"] = ScanStatus.FAILED
        SCAN_JOBS[job_id]["error"] = f"Scan failed: {str(e)}"

    finally:
        # Cleanup
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
                # Remove parent temp directory
                temp_dir = os.path.dirname(zip_path)
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Scan {job_id}: Cleaned up temporary files")
            except Exception as e:
                logger.error(f"Scan {job_id}: Cleanup failed - {e}")
