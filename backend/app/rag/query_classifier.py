from __future__ import annotations

from typing import Any


class QueryClassifier:
    """
    Lightweight deterministic query classifier.

    Routes retrieval to the most relevant knowledge source
    before invoking the RAG layer.
    """

    INTENTS = (
        "medical",
        "claims",
        "policy",
        "coverage",
        "regulatory",
        "underwriting",
        "broad",
    )

    KEYWORDS: dict[str, tuple[str, ...]] = {
        "coverage": (
            "coverage gap",
            "coverage gaps",
            "coverage adequacy",
            "coverage limitation",
            "coverage limitations",
            "missing coverage",
            "insufficient coverage",
            "underinsurance",
            "underinsured",
        ),
        "claims": (
            "claim",
            "claims",
            "hospitalization",
            "hospitalisation",
            "admission",
            "admitted",
            "claim history",
            "utilization",
            "utilisation",
        ),
        "policy": (
            "policy",
            "sum insured",
            "deductible",
            "existing policy",
            "policy term",
            "benefit",
            "exclusion",
        ),
        "regulatory": (
            "irdai",
            "regulation",
            "regulatory",
            "compliance",
            "circular",
            "regulator",
            "health insurance rule",
            "legal requirement",
        ),
        "underwriting": (
            "underwriting",
            "underwriter",
            "risk assessment",
            "risk score",
            "loading",
            "premium",
            "pricing",
            "acceptance",
            "decline",
            "risk",
        ),
        "medical": (
            "medical",
            "diagnosis",
            "diagnoses",
            "disease",
            "condition",
            "symptom",
            "comorbidity",
            "complication",
            "medication",
            "medicine",
            "drug",
            "treatment",
            "lab",
            "laboratory",
            "blood",
            "diabetes",
            "hypertension",
            "cancer",
            "cardiac",
            "heart",
            "asthma",
            "arthritis",
            "thyroid",
        ),
    }

    PRIORITY = (
        "coverage",
        "claims",
        "policy",
        "regulatory",
        "underwriting",
        "medical",
    )

    def classify(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = self._normalize(query)

        if not text:
            return {
                "intent": "broad",
                "confidence": 0.0,
                "matched_keywords": [],
                "scores": {},
            }

        scores: dict[str, int] = {
            intent: 0
            for intent in self.INTENTS
            if intent != "broad"
        }

        matched: dict[str, list[str]] = {
            intent: []
            for intent in scores
        }

        for intent, keywords in self.KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    scores[intent] += self._keyword_weight(
                        keyword
                    )
                    matched[intent].append(keyword)

        best_intent = self._select_intent(
            scores
        )

        if best_intent == "broad":
            confidence = 0.50
        else:
            confidence = self._calculate_confidence(
                scores,
                best_intent,
            )

        return {
            "intent": best_intent,
            "confidence": confidence,
            "matched_keywords": matched.get(
                best_intent,
                [],
            ),
            "scores": scores,
        }

    def classify_intent(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        return self.classify(
            query=query,
            context=context,
        )["intent"]

    def _select_intent(
        self,
        scores: dict[str, int],
    ) -> str:
        if not scores:
            return "broad"

        highest = max(
            scores.values()
        )

        if highest <= 0:
            return "broad"

        candidates = [
            intent
            for intent in self.PRIORITY
            if scores.get(intent, 0) == highest
        ]

        return (
            candidates[0]
            if candidates
            else "broad"
        )

    @staticmethod
    def _keyword_weight(
        keyword: str,
    ) -> int:
        if " " in keyword:
            return 2

        return 1

    @staticmethod
    def _calculate_confidence(
        scores: dict[str, int],
        selected_intent: str,
    ) -> float:
        selected = scores.get(
            selected_intent,
            0,
        )

        if selected <= 0:
            return 0.50

        total = sum(
            scores.values()
        )

        if total <= 0:
            return 0.50

        confidence = selected / total

        return round(
            min(
                0.98,
                max(
                    0.60,
                    confidence,
                ),
            ),
            3,
        )

    @staticmethod
    def _normalize(
        query: str,
    ) -> str:
        return " ".join(
            str(query or "")
            .lower()
            .strip()
            .split()
        )


query_classifier = QueryClassifier()