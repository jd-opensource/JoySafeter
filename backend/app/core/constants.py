"""
Core constants for the application.

Centralized location for shared constants to ensure consistency across modules.
"""

from enum import StrEnum

# Default user ID: nil UUID (00000000-0000-0000-0000-000000000000)
# Using nil UUID ensures type consistency and avoids confusion with real UUIDs.
# This is used when user_id is None or not provided, ensuring all user_id values
# are strings in UUID format.
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000000"


class TriggerMedium(StrEnum):
    SYSTEM = "system"
    API = "api"
    UI = "ui"


class RunPurpose(StrEnum):
    PRODUCTION = "production"
    DRAFT_TEST = "draft_test"
    INTERNAL_BUILDER = "internal_builder"
    DEBUG = "debug"
