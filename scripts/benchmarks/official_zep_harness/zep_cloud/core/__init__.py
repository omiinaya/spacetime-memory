"""zep_cloud.core — shim for the harness's retry logic."""


class ApiError(Exception):
    """Error raised by Zep API calls (retried by the harness)."""

    def __init__(self, message: str = "", status_code: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body


__all__ = ["ApiError"]
