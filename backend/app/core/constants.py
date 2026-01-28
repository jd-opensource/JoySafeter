"""
Core constants for the application.

Centralized location for shared constants to ensure consistency across modules.
"""

# Default user ID: nil UUID (00000000-0000-0000-0000-000000000000)
# Using nil UUID ensures type consistency and avoids confusion with real UUIDs.
# This is used when user_id is None or not provided, ensuring all user_id values
# are strings in UUID format.
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000000"
