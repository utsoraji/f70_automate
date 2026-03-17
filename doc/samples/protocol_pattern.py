from __future__ import annotations
from typing import Protocol, TYPE_CHECKING

# =================================================================
# PATTERN A: Consumer-Driven (Internal Logic)
# Define what your business logic needs.
# =================================================================
class Storage(Protocol):
    def save(self, data: str) -> None: ...

# =================================================================
# PATTERN B: External-Driven (Adapters/Wrappers)
# Mirror an external SDK's signature to allow Mocking.
# =================================================================
class ExternalS3ClientLike(Protocol):
    """Reflects the signature of an external library (e.g., boto3)."""
    def put_object(self, Bucket: str, Key: str, Body: bytes) -> dict: ...

# --- Implementation (The Wrapper) ---
class S3Adapter:
    """Wraps the real external library. No Protocol inheritance here."""
    def put_object(self, Bucket: str, Key: str, Body: bytes) -> dict:
        # Real SDK call: self.client.put_object(...)
        return {"Status": "OK"}

# --- Verification ---
if TYPE_CHECKING:
    # Ensures our Adapter correctly mirrors the External SDK's required API
    _: ExternalS3ClientLike = S3Adapter()

# =================================================================
# MOCKING (Crucial for External-Driven)
# =================================================================
class MockS3Client(ExternalS3ClientLike):
    """
    Mocks MUST inherit from Protocol.
    This ensures that if the External API changes, the Mock fails type-check.
    """
    def put_object(self, Bucket: str, Key: str, Body: bytes) -> dict:
        return {"Status": "Mocked"}
