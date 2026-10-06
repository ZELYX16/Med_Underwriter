from __future__ import annotations

import re
from typing import Any, Literal


QueryIntent = Literal[
    "medical",
    "claims",
    "policy",
    "regulatory",
    "underwriting",
    "broad",
]


class QueryClassifier:
    """
    Classifies an underwriting retrieval query into a
    retrieval domain.

    This is intentionally deterministic for the first POC.
    A model-based classifier can be added later without
    changing the RAG interface.
    """

    INTENT_PATTERNS: dict[str, tuple[str, ...]] = {
        "regulatory": (
            "irdai",
            "regulation",
            "regulatory",
            "circular",
            "compliance",
            "regulator",
            "mandate",
            "legal requirement",
            "regulatory requirement",
            "insurance authority",
        ),
        "underwriting": (
            "underwriting",
            "underwriter",
            "eligibility",
            "risk class",
            "risk assessment",
            "risk score",
            "loading",
            "premium",
            "pricing",
            "acceptance",
            "decline",
            "exclusion",
            "insurability",
        ),
        "claims": (
            "claim",
            "claims",
            "claim history",
            "claim frequency",
            "claim amount",
            "paid claim",
            "hospital claim",
            "previous claim",
        ),
        "policy": (
            "policy",
            "coverage",
            "covered",
            "coverage limit",
            "sum insured",
            "deductible",
            "existing cover",
            "existing policy",
            "benefit",
            "exclusion",
            "waiting period",
        ),
        "medical": (
            "diagnosis",
            "disease",
            "condition",
            "medical condition",
            "symptom",
            "medication",
            "medicine",
            "drug",
            "comorbidity",
            "treatment",
            "laboratory",
            "lab result",
            "hospitalization",
            "hospitalisation",
            "surgery",
            "procedure",
            "clinical",
            "medical history",
            "hypertension",
            "diabetes",
            "asthma",
            "arthritis",
            "cancer",
            "cardiac",
            "renal",
            "thyroid",
            "cholesterol",
        ),
    }

    PRIORITY = (
        "regulatory",
        "underwriting",
        "claims",
        "policy",
        "medical",
    )

    def classify(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not query or not query.strip():
            return {
                "intent": "broad",
                "confidence": 0.0,
                "matched_terms": [],
                "reason": "Empty query.",
            }

        normalized = self._normalize(query)

        scores: dict[str, int] = {
            intent: 0
            for intent in self.INTENT_PATTERNS
        }

        matches: dict[str, list[str]] = {
            intent: []
            for intent in self.INTENT_PATTERNS
        }

        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if self._matches(
                    normalized,
                    pattern,
                ):
                    scores[intent] += 1
                    matches[intent].append(pattern)

        selected_intent = self._select_intent(
            scores
        )

        selected_matches = matches.get(
            selected_intent,
            [],
        )

        confidence = self._calculate_confidence(
            scores,
            selected_intent,
        )

        return {
            "intent": selected_intent,
            "confidence": confidence,
            "matched_terms": selected_matches,
            "scores": scores,
            "reason": self._build_reason(
                selected_intent,
                selected_matches,
            ),
        }

    def classify_many(
        self,
        queries: list[str],
    ) -> list[dict[str, Any]]:
        return [
            self.classify(query)
            for query in queries
        ]

    def _normalize(
        self,
        text: str,
    ) -> str:
        text = text.lower()
        text = re.sub(
            r"\s+",
            " ",
            text,
        )
        return text.strip()

    def _matches(
        self,
        text: str,
        pattern: str,
    ) -> bool:
        normalized_pattern = self._normalize(
            pattern
        )

        if " " in normalized_pattern:
            return normalized_pattern in text

        return bool(
            re.search(
                rf"\b{re.escape(normalized_pattern)}\b",
                text,
            )
        )

    def _select_intent(
        self,
        scores: dict[str, int],
    ) -> QueryIntent:
        max_score = max(
            scores.values(),
            default=0,
        )

        if max_score == 0:
            return "broad"

        candidates = [
            intent
            for intent in self.PRIORITY
            if scores.get(intent, 0) == max_score
        ]

        return candidates[0]  # type: ignore[return-value]

    def _calculate_confidence(
        self,
        scores: dict[str, int],
        selected_intent: str,
    ) -> float:
        if selected_intent == "broad":
            return 0.0

        selected_score = scores.get(
            selected_intent,
            0,
        )

        if selected_score == 0:
            return 0.0

        total_score = sum(
            scores.values()
        )

        if total_score == 0:
            return 0.0

        confidence = (
            selected_score / total_score
        )

        return round(
            min(confidence, 1.0),
            3,
        )

    def _build_reason(
        self,
        intent: str,
        matched_terms: list[str],
    ) -> str:
        if intent == "broad":
            return (
                "No strong retrieval-domain "
                "indicator was detected."
            )

        if not matched_terms:
            return (
                f"Query classified as {intent}."
            )

        return (
            f"Query classified as {intent} "
            f"based on: "
            f"{', '.join(matched_terms)}."
        )


query_classifier = QueryClassifier()