import re
from typing import Any


class GuardrailResult:
    def __init__(
        self,
        allowed: bool,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ):
        self.allowed = allowed
        self.errors = errors or []
        self.warnings = warnings or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class UnderwritingGuardrails:
    MAX_TEXT_LENGTH = 20_000
    MAX_LIST_ITEMS = 100

    BLOCKED_PATTERNS = [
        r"<script\b",
        r"javascript:",
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(all\s+)?previous\s+instructions",
        r"system\s*prompt",
        r"developer\s+message",
    ]

    REQUIRED_APPLICANT_FIELDS = [
        "applicant",
        "underwriting_request",
    ]

    def validate_submission(
        self,
        submission: dict[str, Any],
    ) -> GuardrailResult:
        errors = []
        warnings = []

        if not isinstance(submission, dict):
            return GuardrailResult(
                allowed=False,
                errors=["Submission must be a JSON object."],
            )

        for field in self.REQUIRED_APPLICANT_FIELDS:
            if field not in submission:
                errors.append(
                    f"Missing required field: {field}"
                )

        if errors:
            return GuardrailResult(
                allowed=False,
                errors=errors,
                warnings=warnings,
            )

        self._validate_applicant(
            submission.get("applicant"),
            errors,
        )

        self._validate_medical(
            submission.get("medical", {}),
            errors,
            warnings,
        )

        self._validate_claims(
            submission.get("claims", []),
            errors,
        )

        self._validate_underwriting_request(
            submission.get(
                "underwriting_request"
            ),
            errors,
        )

        self._scan_for_prompt_injection(
            submission,
            errors,
        )

        return GuardrailResult(
            allowed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def validate_query(
        self,
        query: str,
    ) -> GuardrailResult:
        errors = []
        warnings = []

        if not isinstance(query, str):
            return GuardrailResult(
                allowed=False,
                errors=["Query must be a string."],
            )

        query = query.strip()

        if not query:
            errors.append(
                "Query cannot be empty."
            )

        if len(query) > self.MAX_TEXT_LENGTH:
            errors.append(
                "Query exceeds the maximum allowed length."
            )

        if self._contains_blocked_pattern(query):
            errors.append(
                "Query contains a blocked instruction pattern."
            )

        return GuardrailResult(
            allowed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def sanitize_text(
        self,
        value: str,
    ) -> str:
        if not isinstance(value, str):
            return ""

        value = value.replace(
            "\x00",
            "",
        )

        value = re.sub(
            r"<script\b[^>]*>.*?</script>",
            "",
            value,
            flags=re.IGNORECASE | re.DOTALL,
        )

        return value.strip()

    def _validate_applicant(
        self,
        applicant: Any,
        errors: list[str],
    ) -> None:
        if not isinstance(applicant, dict):
            errors.append(
                "Applicant must be an object."
            )
            return

        applicant_id = applicant.get(
            "applicant_id"
        )

        if not applicant_id:
            errors.append(
                "Applicant ID is required."
            )
        elif not self._valid_identifier(
            applicant_id
        ):
            errors.append(
                "Applicant ID contains invalid characters."
            )

        age = applicant.get("age")

        if age is not None:
            if not isinstance(age, int):
                errors.append(
                    "Applicant age must be an integer."
                )
            elif age < 0 or age > 120:
                errors.append(
                    "Applicant age must be between 0 and 120."
                )

    def _validate_medical(
        self,
        medical: Any,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        if not isinstance(medical, dict):
            errors.append(
                "Medical information must be an object."
            )
            return

        for field in [
            "conditions",
            "icd10_codes",
            "medications",
            "procedures",
        ]:
            value = medical.get(
                field,
                [],
            )

            if not isinstance(value, list):
                errors.append(
                    f"Medical field '{field}' must be a list."
                )
                continue

            if len(value) > self.MAX_LIST_ITEMS:
                errors.append(
                    f"Medical field '{field}' contains too many items."
                )

        if not medical.get("conditions"):
            warnings.append(
                "No medical conditions were provided."
            )

    def _validate_claims(
        self,
        claims: Any,
        errors: list[str],
    ) -> None:
        if not isinstance(claims, list):
            errors.append(
                "Claims must be a list."
            )
            return

        if len(claims) > self.MAX_LIST_ITEMS:
            errors.append(
                "Submission contains too many claims."
            )

        for index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                errors.append(
                    f"Claim {index} must be an object."
                )
                continue

            if not claim.get("claim_id"):
                errors.append(
                    f"Claim {index} is missing claim_id."
                )

    def _validate_underwriting_request(
        self,
        request: Any,
        errors: list[str],
    ) -> None:
        if not isinstance(request, dict):
            errors.append(
                "Underwriting request must be an object."
            )
            return

        product = request.get("product")

        if not isinstance(product, str) or not product.strip():
            errors.append(
                "Underwriting product is required."
            )

        sum_insured = request.get(
            "sum_insured"
        )

        if not isinstance(
            sum_insured,
            (int, float),
        ):
            errors.append(
                "Sum insured must be numeric."
            )
        elif sum_insured <= 0:
            errors.append(
                "Sum insured must be greater than zero."
            )

        policy_term = request.get(
            "policy_term_years",
            1,
        )

        if not isinstance(policy_term, int):
            errors.append(
                "Policy term must be an integer."
            )
        elif policy_term < 1 or policy_term > 10:
            errors.append(
                "Policy term must be between 1 and 10 years."
            )

    def _scan_for_prompt_injection(
        self,
        value: Any,
        errors: list[str],
    ) -> None:
        text_values = self._extract_strings(
            value
        )

        for text in text_values:
            if self._contains_blocked_pattern(
                text
            ):
                errors.append(
                    "Potential prompt injection detected "
                    "in submission content."
                )
                return

    def _contains_blocked_pattern(
        self,
        value: str,
    ) -> bool:
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(
                pattern,
                value,
                flags=re.IGNORECASE,
            ):
                return True

        return False

    @staticmethod
    def _valid_identifier(
        value: Any,
    ) -> bool:
        if not isinstance(value, str):
            return False

        return bool(
            re.fullmatch(
                r"[A-Za-z0-9_-]+",
                value,
            )
        )

    @staticmethod
    def _extract_strings(
        value: Any,
    ) -> list[str]:
        if isinstance(value, str):
            return [value]

        if isinstance(value, dict):
            strings = []

            for item in value.values():
                strings.extend(
                    UnderwritingGuardrails._extract_strings(
                        item
                    )
                )

            return strings

        if isinstance(value, list):
            strings = []

            for item in value:
                strings.extend(
                    UnderwritingGuardrails._extract_strings(
                        item
                    )
                )

            return strings

        return []


guardrails = UnderwritingGuardrails()