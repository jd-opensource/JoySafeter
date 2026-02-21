import os
import sys

# Add backend to path
sys.path.append(os.getcwd())

try:
    from app.services.test_service import TestService  # noqa: F401

    print("✅ Successfully imported TestService")
except ImportError as e:
    print(f"❌ Failed to import TestService: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ An error occurred: {e}")
    sys.exit(1)
