from __future__ import annotations

from typing import Any

from app.config import settings
from app.store.vector_store import vector_store


class MedGraphRAG:
    """
    MedGraphRAG-inspired medical retrieval layer.

    The medical graph concept connects:
        applicant evidence
            ↓
        medical concepts
            ↓
        disease / medication / comorbidity relationships
            ↓
        relevant medical evidence

    Medical knowledge is kept separate from regulatory
    and underwriting knowledge.
    """

    MEDICAL_COLLECTION = "medical_knowledge"
    APPLICANT_COLLECTION = "applicant_documents"

    def __init__(self) -> None:
        self.top_k = settings.top_k_results

    def _search(
        self,
        collection_name: str,
        query: str,
        top_k: int | None = None,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []

        limit = top_k or self.top_k

        try:
            results = vector_store.query(
                collection_name=collection_name,
                query_text=query,
                n_results=limit,
                where=where,
            )
        except Exception:
            return []

        return self._normalize_results(results)

    def _normalize_results(
        self,
        results: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not results:
            return []

        documents = results.get(
            "documents",
            [[]],
        )

        metadatas = results.get(
            "metadatas",
            [[]],
        )

        distances = results.get(
            "distances",
            [[]],
        )

        documents = (
            documents[0]
            if documents
            else []
        )

        metadatas = (
            metadatas[0]
            if metadatas
            else []
        )

        distances = (
            distances[0]
            if distances
            else []
        )

        output: list[dict[str, Any]] = []

        for index, document in enumerate(
            documents
        ):
            metadata = (
                metadatas[index]
                if index < len(metadatas)
                else {}
            )

            distance = (
                distances[index]
                if index < len(distances)
                else None
            )

            output.append(
                {
                    "content": document,
                    "metadata": metadata or {},
                    "distance": distance,
                    "source": metadata.get(
                        "source",
                        "unknown",
                    ),
                    "concept_id": metadata.get(
                        "concept_id"
                    ),
                    "concept_type": metadata.get(
                        "concept_type"
                    ),
                    "concept_name": metadata.get(
                        "concept_name"
                    ),
                }
            )

        return output

    def search_medical_knowledge(
        self,
        query: str,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """
        Search the medical knowledge collection.

        Expected knowledge sources include:
        - ICD-10-CM
        - RxNorm
        - medical reference material
        """

        results = self._search(
            collection_name=self.MEDICAL_COLLECTION,
            query=query,
            top_k=top_k,
        )

        return {
            "query": query,
            "results": results,
            "result_count": len(results),
        }

    def search_applicant_evidence(
        self,
        applicant_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve medical evidence belonging to one applicant.
        """

        if not applicant_id:
            return []

        return self._search(
            collection_name=self.APPLICANT_COLLECTION,
            query=query,
            top_k=top_k,
            where={
                "$and": [
                    {
                        "applicant_id": applicant_id
                    },
                    {
                        "document_type": "medical"
                    },
                ]
            },
        )

    def retrieve_medical_concepts(
        self,
        conditions: list[str],
        medications: list[str],
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve medical knowledge for the applicant's
        conditions and medications.
        """

        condition_results: list[
            dict[str, Any]
        ] = []

        medication_results: list[
            dict[str, Any]
        ] = []

        for condition in conditions:
            condition_results.extend(
                self._search(
                    collection_name=self.MEDICAL_COLLECTION,
                    query=condition,
                    top_k=top_k,
                )
            )

        for medication in medications:
            medication_results.extend(
                self._search(
                    collection_name=self.MEDICAL_COLLECTION,
                    query=medication,
                    top_k=top_k,
                )
            )

        return {
            "conditions": conditions,
            "medications": medications,
            "condition_knowledge": condition_results,
            "medication_knowledge": medication_results,
        }

    def retrieve_for_applicant(
        self,
        applicant_id: str,
        applicant_profile: dict[str, Any],
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """
        Main MedGraphRAG retrieval entry point for Agent 1.
        """

        conditions = self._extract_conditions(
            applicant_profile
        )

        medications = self._extract_medications(
            applicant_profile
        )

        condition_query = (
            ", ".join(conditions)
            if conditions
            else "general medical health"
        )

        medical_evidence = (
            self.search_applicant_evidence(
                applicant_id=applicant_id,
                query=condition_query,
                top_k=top_k,
            )
        )

        medical_knowledge = (
            self.retrieve_medical_concepts(
                conditions=conditions,
                medications=medications,
                top_k=top_k,
            )
        )

        relationships = self._build_relationships(
            conditions=conditions,
            medications=medications,
            knowledge=medical_knowledge,
        )

        return {
            "applicant_id": applicant_id,
            "conditions": conditions,
            "medications": medications,
            "medical_evidence": medical_evidence,
            "medical_knowledge": medical_knowledge,
            "relationships": relationships,
            "evidence_count": len(
                medical_evidence
            ),
        }

    def _extract_conditions(
        self,
        applicant_profile: dict[str, Any],
    ) -> list[str]:
        conditions = applicant_profile.get(
            "medical_conditions",
            applicant_profile.get(
                "conditions",
                [],
            ),
        )

        if isinstance(
            conditions,
            str,
        ):
            return [conditions]

        return [
            str(condition)
            for condition in conditions
            if condition
        ]

    def _extract_medications(
        self,
        applicant_profile: dict[str, Any],
    ) -> list[str]:
        medications = applicant_profile.get(
            "medications",
            [],
        )

        if isinstance(
            medications,
            str,
        ):
            return [medications]

        return [
            str(medication)
            for medication in medications
            if medication
        ]

    def _build_relationships(
        self,
        conditions: list[str],
        medications: list[str],
        knowledge: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build a lightweight relationship representation.

        This does not invent medical relationships. It only
        connects concepts when they are present in retrieved
        knowledge metadata.
        """

        relationships: list[
            dict[str, Any]
        ] = []

        condition_knowledge = knowledge.get(
            "condition_knowledge",
            [],
        )

        medication_knowledge = knowledge.get(
            "medication_knowledge",
            [],
        )

        for result in (
            condition_knowledge
            + medication_knowledge
        ):
            metadata = result.get(
                "metadata",
                {},
            )

            relation_type = metadata.get(
                "relation_type"
            )

            source_concept = metadata.get(
                "source_concept"
            )

            target_concept = metadata.get(
                "target_concept"
            )

            if (
                relation_type
                and source_concept
                and target_concept
            ):
                relationships.append(
                    {
                        "source": source_concept,
                        "relation": relation_type,
                        "target": target_concept,
                        "source_document": result.get(
                            "source"
                        ),
                    }
                )

        return relationships


medgraph_rag = MedGraphRAG()