"""Custom exception types for the RAG package."""

class RagError(Exception):
    """Base exception for RAG-related errors."""


class ProfileNotConfiguredError(RagError):
    """Raised when USER_PROFILE is missing."""


__all__ = ["RagError", "ProfileNotConfiguredError"]
