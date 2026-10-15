"""Structured, configuration-independent SQL policy decisions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    error_code: str | None = None
    message: str | None = None
    hint: str | None = None

    @classmethod
    def allow(cls) -> "PolicyDecision":
        return cls(True)

    @classmethod
    def deny(cls, code: str, message: str, hint: str | None = None) -> "PolicyDecision":
        return cls(False, code, message, hint)

    def error_payload(self) -> dict:
        if self.allowed:
            raise ValueError("An allowed decision has no error payload")
        payload = {"success": False, "error_code": self.error_code, "error": self.message}
        if self.hint:
            payload["hint"] = self.hint
        return payload
