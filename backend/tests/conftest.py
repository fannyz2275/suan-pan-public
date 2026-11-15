import os
import pytest

# Set required env vars before any app module is imported
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")
os.environ.setdefault("PLAID_CLIENT_ID", "test-plaid-id")
os.environ.setdefault("PLAID_SECRET", "test-plaid-secret")


# JSON-format syrupy fixture available to all tests (Spec B §13 migration).
# Tests under tests/evals/backend/ get the same fixture from their local
# conftest; both definitions are equivalent.
@pytest.fixture
def snapshot_json(snapshot):
    from syrupy.extensions.json import JSONSnapshotExtension
    return snapshot.use_extension(JSONSnapshotExtension)
