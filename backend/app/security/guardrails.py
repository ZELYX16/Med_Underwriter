from __future__ import annotations

import re
from typing import Any

from app.config import settings


class GuardrailResult:
    def __init__(
        self,
        allowed: bool,
        risk_level: str,
        reasons: list[str],
        sanitized_prompt: str,
        checks: dict[str, Any],
    ) -> None:
        self.allowed = allowed
        self.risk_level = risk_level
        self.reasons = reasons
        self.sanitized_prompt = sanitized_prompt
        self.checks = checks

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "risk_level": self.risk_level,
            "reasons": self.reasons,
            "sanitized_prompt": self.sanitized_prompt,
            "checks": self.checks,
        }


class Guardrails:
    """
    Security and safety validation layer for LLM requests.

    The guardrail is intentionally deterministic so that unsafe input
    is rejected before it reaches an LLM.
    """

    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+(all\s+)?prior\s+instructions",
        r"disregard\s+(all\s+)?previous\s+instructions",
        r"forget\s+(all\s+)?previous\s+instructions",
        r"system\s+prompt",
        r"reveal\s+(your\s+)?hidden\s+instructions",
        r"show\s+(your\s+)?hidden\s+prompt",
        r"developer\s+message",
        r"jailbreak",
        r"bypass\s+(the\s+)?safety",
        r"disable\s+(the\s+)?guardrails",
    ]

    SECRET_PATTERNS = [
        r"sk-[A-Za-z0-9]{20,}",
        r"ghp_[A-Za-z0-9]{20,}",
        r"AIza[A-Za-z0-9_-]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN\s+(RSA|OPENSSH|EC|PRIVATE)\s+KEY-----",
    ]

    PII_PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "phone": r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)",
        "aadhaar": r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)",
        "pan": r"\b[A-Z]{5}\d{4}[A-Z]\b",
    }

    MEDICAL_DECISION_PATTERNS = [
        r"guarantee\s+(acceptance|approval)",
        r"guarantee\s+coverage",
        r"automatically\s+approve",
        r"automatically\s+reject",
        r"deny\s+because\s+of\s+race",
        r"deny\s+because\s+of\s+religion",
        r"deny\s+because\s+of\s+gender",
        r"deny\s+because\s+of\s+caste",
    ]

    def __init__(self) -> None:
        self.enabled = True

    def validate_prompt(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        if not isinstance(prompt, str):
            return GuardrailResult(
                allowed=False,
                risk_level="high",
                reasons=["Prompt must be a string."],
                sanitized_prompt="",
                checks={"input_type": False},
            )

        if not prompt.strip():
            return GuardrailResult(
                allowed=False,
                risk_level="high",
                reasons=["Prompt cannot be empty."],
                sanitized_prompt="",
                checks={"non_empty": False},
            )

        reasons: list[str] = []
        checks: dict[str, Any] = {}

        normalized = self._normalize(prompt)

        injection_matches = self._find_matches(
            normalized,
            self.INJECTION_PATTERNS,
        )

        secret_matches = self._find_matches(
            prompt,
            self.SECRET_PATTERNS,
        )

        medical_decision_matches = self._find_matches(
            normalized,
            self.MEDICAL_DECISION_PATTERNS,
        )

        pii_matches = self._find_pii(prompt)

        checks["prompt_injection"] = {
            "passed": not injection_matches,
            "matches": injection_matches,
        }

        checks["secrets"] = {
            "passed": not secret_matches,
            "matches": secret_matches,
        }

        checks["pii"] = {
            "passed": True,
            "detected": pii_matches,
        }

        checks["medical_decision_safety"] = {
            "passed": not medical_decision_matches,
            "matches": medical_decision_matches,
        }

        if injection_matches:
            reasons.append(
                "Potential prompt injection or instruction override detected."
            )

        if secret_matches:
            reasons.append(
                "Potential API key or secret detected in the prompt."
            )

        if medical_decision_matches:
            reasons.append(
                "Prompt attempts to force an unsafe or predetermined "
                "underwriting decision."
            )

        sanitized_prompt = self._sanitize(prompt)

        if pii_matches:
            reasons.append(
                "Potential personal identifiers detected and masked."
            )

        if len(prompt) > 30000:
            reasons.append("Prompt exceeds the maximum permitted length.")

        checks["length"] = {
            "passed": len(prompt) <= 30000,
            "characters": len(prompt),
        }

        checks["context"] = self._validate_context(context)

        hard_block = bool(
            injection_matches
            or secret_matches
            or medical_decision_matches
            or len(prompt) > 30000
        )

        risk_level = self._risk_level(
            hard_block=hard_block,
            pii_detected=bool(pii_matches),
        )

        return GuardrailResult(
            allowed=not hard_block,
            risk_level=risk_level,
            reasons=self._unique(reasons),
            sanitized_prompt=sanitized_prompt,
            checks=checks,
        )

    def validate_submission(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
    ) -> GuardrailResult:
        if not isinstance(applicant_profile, dict):
            return GuardrailResult(
                allowed=False,
                risk_level="high",
                reasons=["Applicant profile must be an object."],
                sanitized_prompt="",
                checks={"applicant_profile": False},
            )

        if not isinstance(submission, dict):
            return GuardrailResult(
                allowed=False,
                risk_level="high",
                reasons=["Submission must be an object."],
                sanitized_prompt="",
                checks={"submission": False},
            )

        serialized = f"{applicant_profile}\n{submission}"

        return self.validate_prompt(
            serialized,
            context={
                "type": "underwriting_submission",
                "applicant_id": applicant_profile.get("applicant_id"),
            },
        )

    def validate_output(
        self,
        output: Any,
    ) -> GuardrailResult:
        if output is None:
            return GuardrailResult(
                allowed=False,
                risk_level="high",
                reasons=["LLM returned an empty response."],
                sanitized_prompt="",
                checks={"output_present": False},
            )

        text = (
            output
            if isinstance(output, str)
            else str(output)
        )

        normalized = self._normalize(text)

        forbidden = [
            r"guaranteed\s+approval",
            r"guaranteed\s+coverage",
            r"guaranteed\s+acceptance",
        ]

        matches = self._find_matches(
            normalized,
            forbidden,
        )

        return GuardrailResult(
            allowed=not bool(matches),
            risk_level="high" if matches else "low",
            reasons=(
                ["Output contains an unsupported guarantee."]
                if matches
                else []
            ),
            sanitized_prompt=text,
            checks={
                "output_present": True,
                "unsupported_guarantee": {
                    "passed": not bool(matches),
                    "matches": matches,
                },
            },
        )

    def _sanitize(self, text: str) -> str:
        sanitized = text

        for name, pattern in self.PII_PATTERNS.items():
            sanitized = re.sub(
                pattern,
                f"[REDACTED_{name.upper()}]",
                sanitized,
                flags=re.IGNORECASE,
            )

        for pattern in self.SECRET_PATTERNS:
            sanitized = re.sub(
                pattern,
                "[REDACTED_SECRET]",
                sanitized,
                flags=re.IGNORECASE,
            )

        return sanitized

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(
            r"\s+",
            " ",
            text.lower().strip(),
        )

    @staticmethod
    def _find_matches(
        text: str,
        patterns: list[str],
    ) -> list[str]:
        matches: list[str] = []

        for pattern in patterns:
            try:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    matches.append(pattern)
            except re.error:
                continue

        return matches

    def _find_pii(self, text: str) -> list[str]:
        detected: list[str] = []

        for name, pattern in self.PII_PATTERNS.items():
            try:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    detected.append(name)
            except re.error:
                continue

        return detected

    @staticmethod
    def _validate_context(
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if context is None:
            return {
                "provided": False,
                "passed": True,
            }

        if not isinstance(context, dict):
            return {
                "provided": True,
                "passed": False,
            }

        return {
            "provided": True,
            "passed": True,
            "keys": list(context.keys())[:20],
        }

    @staticmethod
    def _risk_level(
        *,
        hard_block: bool,
        pii_detected: bool,
    ) -> str:
        if hard_block:
            return "high"

        if pii_detected:
            return "medium"

        return "low"

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []

        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)

        return result


guardrails = Guardrails()