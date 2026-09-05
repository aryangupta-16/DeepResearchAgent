"""Domain exception hierarchy.

HTTP dependencies map these exceptions to HTTP responses; infrastructure-level
errors should be wrapped here rather than leaking vendor specifics to callers.
"""

from typing import Literal


class AppError(Exception):
    """Base class for all application-level errors."""

    status_code: Literal[400, 404, 409, 422, 500, 502, 503] = 500
    code: str = "app_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ResearchJobNotFoundError(NotFoundError):
    """A research job with the requested id does not exist."""

    code = "research_job_not_found"


class ResearchTaskNotFoundError(NotFoundError):
    """A research task with the requested id does not exist."""

    code = "research_task_not_found"


class ResearchJobInvalidStateError(AppError):
    """Raised when a state transition is not allowed for a research job."""

    status_code = 409
    code = "research_job_invalid_state"


class DocumentInvalidStateError(AppError):
    """Raised when an operation conflicts with a document's current state."""

    status_code = 409
    code = "document_invalid_state"


class PlannerError(AppError):
    """Raised when the planner agent fails or produces invalid output."""

    status_code = 502
    code = "planner_error"


class ResearcherError(AppError):
    """Raised when a researcher agent fails or produces invalid output."""

    status_code = 502
    code = "researcher_error"


class SynthesisError(AppError):
    """Raised when the synthesizer agent fails or produces invalid output."""

    status_code = 502
    code = "synthesis_error"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class NotConfiguredError(AppError):
    """Raised when an optional integration (LLM, search, etc.) has no provider set."""

    status_code = 501
    code = "not_configured"


class LLMNotConfiguredError(AppError):
    """Raised when no/invalid LLM provider is configured or an API key is missing."""

    status_code = 503
    code = "llm_not_configured"


class LLMProviderError(AppError):
    """Raised when an LLM provider request fails at the upstream provider."""

    status_code = 502
    code = "llm_provider_error"


class LLMRequestError(AppError):
    """Raised for LLM requests rejected by the provider (e.g. authentication)."""

    status_code = 502
    code = "llm_request_error"


class NotImplementedError(AppError):
    """Raised by placeholder code that is designed but not yet built.

    Note: distinct from Python's builtin ``NotImplementedError``.
    """

    status_code = 501
    code = "not_implemented"


class ToolError(AppError):
    """Raised when a deterministic tool (search/fetch/etc.) fails."""

    status_code = 502
    code = "tool_error"


class SearchError(ToolError):
    """Raised by the search tool/provider layer."""

    status_code = 502
    code = "search_error"


class FetchError(ToolError):
    """Raised by the browser/fetch tool."""

    status_code = 502
    code = "fetch_error"


class EvidenceNotFoundError(NotFoundError):
    """A source or evidence record does not exist."""

    code = "evidence_not_found"


class EvidenceError(AppError):
    """Raised when evidence persistence violates provenance rules."""

    status_code = 502
    code = "evidence_error"


class CitationValidationError(AppError):
    """Raised when a research report contains invalid or orphan citations."""

    status_code = 502
    code = "citation_validation_error"


class MemoryNotFoundError(NotFoundError):
    """A long-term memory with the requested id does not exist."""

    code = "memory_not_found"


class ConversationNotFoundError(NotFoundError):
    """A chat conversation with the requested id does not exist."""

    code = "conversation_not_found"


class MemoryExtractionError(AppError):
    """Raised when LLM memory extraction cannot complete (not a persistence error)."""

    status_code = 502
    code = "memory_extraction_error"