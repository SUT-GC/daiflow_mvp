"""Unified exception hierarchy for DaiFlow services.

Services raise these domain exceptions instead of HTTPException or raw ValueError.
Routers catch them and convert to appropriate HTTP responses.
"""


class DaiFlowError(Exception):
    """Base exception for all DaiFlow domain errors."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class NotFoundError(DaiFlowError):
    """Raised when a requested entity does not exist."""

    def __init__(self, message: str = "Not found"):
        super().__init__(message, status_code=404)


class InvalidStateError(DaiFlowError):
    """Raised when an operation is invalid for the current entity state."""

    def __init__(self, message: str = "Invalid state for this operation"):
        super().__init__(message, status_code=400)


class ConfigurationError(DaiFlowError):
    """Raised when required configuration is missing or invalid."""

    def __init__(self, message: str = "Configuration error"):
        super().__init__(message, status_code=500)
