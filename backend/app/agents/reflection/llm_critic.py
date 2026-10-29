"""
LLM critique for Agent 3.

The rule-based constitutional checks and persona reviews stay the safety
net. For complex / high-risk cases this adds one LLM call that reads the
decision and Agent 2's rationale and argues against them, which catches
problems rules cannot (a rationale that contradicts the scores, an unsound
loading, unsupported statements).

The critique can only add caution: concerns become advisory findings, and an
explicit "disagree" forces human review. It never lowers a risk score or
overrides a recommendation. Any failure returns ok=False and the rule-based
result stands on its own.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.config import settings
from app.llm.factory import get_llm
from app.llm.timing import extract_timing
from app.security.guardrails import guardrails

logger = logging.getLogger(__name__)

PERSONAS = (
    "medical_expert",
    "actuary",
    "compliance_officer",
    "customer_advocate",
)


class LLMCritic:
    def __init__(self) -> None:
        self.llm: Any = None

    def critique(
        self,
        applicant_profile: dict[str, Any],
        risk_assessment: dict[str, Any],
        pricing_result: dict[str, Any],
        recommendation: str,
        reasoning: str,
        rule_concerns: list[str],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            if self.llm is None:
                self.llm = get_llm(
                    "reflection",
                    max_tokens=settings.reflection_max_tokens,
                    json_mode=True,
                )

            prompt = self._prompt(
                applicant_profile,
                risk_assessment,
                pricing_result,
                recommendation,
                reasoning,
                rule_concerns,
            )
            llm_started = time.perf_counter()
            response = self.llm.invoke(prompt)
            llm_latency = round(time.perf_counter() - llm_started, 4)

            content = getattr(response, "content", response)
            if isinstance(content, list):
                content = " ".join(
                    str(i.get("text", i)) if isinstance(i, dict) else str(i)
                    for i in content
                )
            raw = str(content).strip()

            usage = self._usage(response, prompt, raw)
            metrics = {
                **usage,
                "llm_latency_sec": llm_latency,
                "latency_sec": round(time.perf_counter() - started, 4),
                "llm_used": True,
                "timing": extract_timing(response),
            }

            # From here a failure still reports the real time and tokens
            # the model spent.
            try:
                if not guardrails.validate_output(raw).allowed:
                    raise ValueError("critique blocked by output guardrails")
                parsed = self._parse(raw)
            except Exception as exc:
                logger.warning("Agent 3 LLM critique unusable: %s", exc)
                return {
                    "ok": False,
                    "error": str(exc)[:200],
                    "metrics": metrics,
                }

            return {
                "ok": True,
                "verdict": parsed["verdict"],
                "concerns": parsed["concerns"],
                "metrics": metrics,
            }
        except Exception as exc:  # critique must never break a case
            logger.warning("Agent 3 LLM critique skipped: %s", exc)
            return {
                "ok": False,
                "error": str(exc)[:200],
                "metrics": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "llm_latency_sec": 0.0,
                    "latency_sec": round(time.perf_counter() - started, 4),
                    "token_source": "none",
                    "llm_used": False,
                },
            }

    @staticmethod
    def _prompt(
        profile: dict[str, Any],
        risk: dict[str, Any],
        pricing: dict[str, Any],
        recommendation: str,
        reasoning: str,
        rule_concerns: list[str],
    ) -> str:
        facts = {
            "age": profile.get("age"),
            "conditions": profile.get("medical_conditions", []),
            "medications": profile.get("medications", []),
        }
        scores = {
            k: risk.get(k)
            for k in (
                "medical_risk_score",
                "claims_risk_score",
                "coverage_gap_score",
                "overall_risk_score",
            )
        }
        money = {
            k: pricing.get(k)
            for k in ("base_premium", "loading_percentage", "final_premium")
        }
        return f"""
You are a senior underwriting reviewer. Critically check the decision below. Look for: rationale that contradicts the scores or facts, loading or recommendation not justified by the risk, unsupported statements, and unfair reliance on protected attributes.

Reply with JSON only, no other text:
{{"verdict": "agree" | "concerns" | "disagree", "concerns": [{{"persona": "medical_expert" | "actuary" | "compliance_officer" | "customer_advocate", "issue": "<one sentence>", "action": "<one sentence>"}}]}}
Use "agree" with an empty list when the decision is sound. At most 2 concerns, each issue and action under 25 words. Use "disagree" only if the recommendation itself is wrong.

FACTS: {json.dumps(facts, default=str)}
SCORES: {json.dumps(scores, default=str)}
RISK FACTORS: {json.dumps(risk.get("risk_factors", [])[:5], default=str)}
PRICING: {json.dumps(money, default=str)}
RECOMMENDATION: {recommendation}
RATIONALE: {reasoning[:1200]}
RULE-BASED CONCERNS: {json.dumps(rule_concerns[:5], default=str)}
""".strip()

    @staticmethod
    def _load_json(raw: str) -> dict[str, Any]:
        """Parse the JSON object, repairing output cut off mid-way."""
        match = re.search(r"\{.*", raw, re.DOTALL)
        if not match:
            raise ValueError("no JSON in critique")
        text = match.group(0)
        try:
            return json.loads(text[: text.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError):
            pass

        # Truncated or malformed: keep what is recoverable.
        verdict = re.search(
            r'"verdict"\s*:\s*"(agree|concerns|disagree)"', text, re.IGNORECASE
        )
        if not verdict:
            raise ValueError("critique JSON unreadable (no verdict)")
        concerns = []
        for item in re.finditer(
            r'"persona"\s*:\s*"([^"]*)"\s*,\s*"issue"\s*:\s*"([^"]*)"'
            r'(?:\s*,\s*"action"\s*:\s*"([^"]*)")?',
            text,
        ):
            concerns.append(
                {
                    "persona": item.group(1),
                    "issue": item.group(2),
                    "action": item.group(3) or "",
                }
            )
        return {"verdict": verdict.group(1), "concerns": concerns}

    @classmethod
    def _parse(cls, raw: str) -> dict[str, Any]:
        data = cls._load_json(raw)
        verdict = str(data.get("verdict", "")).strip().lower()
        if verdict not in {"agree", "concerns", "disagree"}:
            raise ValueError(f"unexpected verdict {verdict!r}")
        concerns = []
        for item in (data.get("concerns") or [])[:3]:
            if not isinstance(item, dict) or not item.get("issue"):
                continue
            persona = str(item.get("persona", "")).strip()
            concerns.append(
                {
                    "persona": persona if persona in PERSONAS else "medical_expert",
                    "issue": str(item["issue"])[:300],
                    "action": str(item.get("action", ""))[:300],
                }
            )
        if verdict == "concerns" and not concerns:
            verdict = "agree"
        return {"verdict": verdict, "concerns": concerns}

    @staticmethod
    def _usage(response: Any, prompt: str, output: str) -> dict[str, Any]:
        usage = getattr(response, "usage_metadata", None)
        if not isinstance(usage, dict):
            meta = getattr(response, "response_metadata", None)
            usage = (
                (meta.get("token_usage") or meta.get("usage"))
                if isinstance(meta, dict)
                else None
            )
        usage = usage if isinstance(usage, dict) else {}
        tokens_in = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        if tokens_in + tokens_out > 0:
            source = "provider"
        else:
            tokens_in = max(1, len(prompt) // 4)
            tokens_out = max(1, len(output) // 4)
            source = "estimated"
        return {
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
            "token_source": source,
        }


llm_critic = LLMCritic()