from __future__ import annotations


class AppError(Exception):
    def __init__(self, error: str, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.error = error
        self.detail = detail
        self.status_code = status_code
