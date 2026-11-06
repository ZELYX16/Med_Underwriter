from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.config import settings
from app.rag.document_loader import document_loader
from app.store.state_store import state_store


class ApplicantRetriever:
    """Applicant evidence retrieval from SQLite metadata and original files only."""

    TYPE_ALIASES = {
        "medical": {"medical", "medical_report", "medical_reports", "medical_documents", "applicant_profile"},
        "claims": {"claims", "claim", "claim_documents"},
        "policy": {"policy", "previous_policy", "policy_documents"},
        "underwriting": {"underwriting", "submission", "proposal", "underwriting_submission"},
    }

    @staticmethod
    def _terms(text: str) -> set[str]:
        ignored = {"the", "and", "for", "with", "from", "that", "this", "applicant", "document", "evidence"}
        return {w.lower() for w in re.findall(r"[a-zA-Z0-9]{3,}", text or "") if w.lower() not in ignored}

    @classmethod
    def _matches_type(cls, actual: str | None, requested: str | None) -> bool:
        if not requested:
            return True
        return (actual or "other").lower() in cls.TYPE_ALIASES.get(requested.lower(), {requested.lower()})

    def search(self, applicant_id: str, query: str, document_type: str | None = None,
               top_k: int | None = None) -> list[dict[str, Any]]:
        if not applicant_id:
            return []
        limit = max(1, min(top_k or settings.top_k_results, 20))
        query_terms = self._terms(query)
        candidates: list[tuple[int, dict[str, Any]]] = []

        for row in state_store.list_applicant_documents(applicant_id):
            doc_type = row.get("document_type") or "other"
            if not self._matches_type(doc_type, document_type):
                continue
            metadata = dict(row.get("metadata") or {})
            path_value = row.get("file_path") or metadata.get("storage_path")
            if not path_value:
                continue
            path = Path(str(path_value))
            if not path.is_file():
                continue
            try:
                chunks = document_loader.load_file(path)
            except Exception:
                continue

            identity = {
                "applicant_id": applicant_id,
                "document_id": row.get("document_id"),
                "document_type": doc_type,
                "filename": row.get("filename") or path.name,
                "file_name": row.get("filename") or path.name,
                "file_path": str(path), "storage_path": str(path),
                "source": row.get("source") or "applicant_file",
                "evidence_scope": "applicant",
            }
            for i, chunk in enumerate(chunks):
                content = str(chunk.get("text") or "").strip()
                if not content:
                    continue
                overlap = len(query_terms & self._terms(content))
                if query_terms and overlap == 0:
                    continue
                chunk_meta = dict(chunk.get("metadata") or {})
                chunk_meta.update(identity)
                chunk_meta["chunk_index"] = i
                result = {
                    "content": content, "metadata": chunk_meta,
                    "distance": None, "applicant_id": applicant_id,
                    "document_type": doc_type, "document_id": row.get("document_id"),
                    "source": identity["source"], "file_name": identity["filename"],
                    "filename": identity["filename"], "title": identity["filename"],
                    "evidence_scope": "applicant",
                }
                candidates.append((overlap if query_terms else 1, result))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in candidates[:limit]]

    def search_by_type(self, applicant_id: str, query: str, document_type: str,
                       top_k: int | None = None) -> list[dict[str, Any]]:
        return self.search(applicant_id, query, document_type, top_k)

    def retrieve_medical_evidence(self, applicant_id: str, query: str = "medical examination diagnosis conditions treatment", top_k: int | None = None) -> list[dict[str, Any]]:
        return self.search_by_type(applicant_id, query, "medical", top_k)

    def retrieve_claims_evidence(self, applicant_id: str, query: str = "claims hospitalization treatment claim history", top_k: int | None = None) -> list[dict[str, Any]]:
        return self.search_by_type(applicant_id, query, "claims", top_k)

    def retrieve_policy_evidence(self, applicant_id: str, query: str = "existing policy coverage sum insured claims policy status", top_k: int | None = None) -> list[dict[str, Any]]:
        return self.search_by_type(applicant_id, query, "policy", top_k)

    def retrieve_underwriting_submission(self, applicant_id: str, query: str = "underwriting submission requested product sum insured declarations", top_k: int | None = None) -> list[dict[str, Any]]:
        return self.search_by_type(applicant_id, query, "underwriting", top_k)

    def retrieve_all(self, applicant_id: str, query: str = "applicant underwriting medical claims policy evidence", top_k: int | None = None) -> dict[str, list[dict[str, Any]]]:
        return {
            "medical": self.retrieve_medical_evidence(applicant_id, query, top_k),
            "claims": self.retrieve_claims_evidence(applicant_id, query, top_k),
            "policy": self.retrieve_policy_evidence(applicant_id, query, top_k),
            "underwriting": self.retrieve_underwriting_submission(applicant_id, query, top_k),
        }

    def group_by_document(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for item in results:
            meta = item.get("metadata") or {}
            doc_id = item.get("document_id") or meta.get("document_id")
            if not doc_id:
                continue
            group = groups.setdefault(str(doc_id), {
                "document_id": doc_id, "filename": item.get("filename") or "Evidence document",
                "document_type": item.get("document_type"), "applicant_id": item.get("applicant_id"),
                "source": item.get("source"), "evidence_scope": "applicant",
                "contents": [], "metadata": meta,
            })
            if item.get("content"):
                group["contents"].append(str(item["content"]).strip())
        output = []
        for group in groups.values():
            contents = list(dict.fromkeys(x for x in group.pop("contents") if x))
            text = "\n\n".join(contents)
            path = (group.get("metadata") or {}).get("file_path")
            try:
                full = document_loader.load_full_text(path) if path and Path(path).is_file() else ""
            except Exception:
                full = ""
            group.update({"retrieved_content": text, "human_readable_content": full or text,
                          "content": full or text, "chunk_count": len(contents)})
            output.append(group)
        return output

    def retrieve_document_views(self, applicant_id: str, query: str, document_type: str | None = None,
                                top_k: int | None = None) -> list[dict[str, Any]]:
        return self.group_by_document(self.search(applicant_id, query, document_type, top_k))

    def has_evidence(self, applicant_id: str, query: str, document_type: str | None = None) -> bool:
        return bool(self.search(applicant_id, query, document_type, top_k=1))


retriever = ApplicantRetriever()
