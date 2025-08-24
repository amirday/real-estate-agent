class RateLimitExceeded(Exception):
    """Raised when the RapidAPI daily budget is exceeded."""
    pass


class DataValidationError(Exception):
    """Raised when external data cannot be validated into our schemas."""
    pass


class NoCompsError(Exception):
    """Raised when no comparable sales are available after fallbacks."""
    pass


class MissingFieldError(Exception):
    """Raised when required subject fields are missing (e.g., sqft)."""
    pass

