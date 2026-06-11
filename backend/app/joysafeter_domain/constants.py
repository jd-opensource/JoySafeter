"""
Core constants for the application.

TriggerMedium and RunPurpose are canonical in core/contracts/execution.py.
Re-exported here for backward compatibility.
"""

from app.joysafeter_domain.contracts.execution import RunPurpose, TriggerMedium

# Default user ID: nil UUID (00000000-0000-0000-0000-000000000000)
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000000"

__all__ = ["DEFAULT_USER_ID", "RunPurpose", "TriggerMedium"]
