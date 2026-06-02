import re
from typing import Any

from app.schemas import SourceChunk, SynthesisCitation, SynthesisResponse


_WORD_RE = re.compile(r"[a-zA-Z0-9_+-]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def synthesize_response(
    query: str,
    sources: list[SourceChunk],
    simulation_kpis: dict[str, Any] | None = None,
    intent_type: str | None = None,
) -> SynthesisResponse:
    useful_sources = [source for source in sources if source.text.strip()]
    ranked_sources = sorted(useful_sources, key=lambda source: source.score, reverse=True)
    selected_sources = ranked_sources[:3]

    citations = [_citation_from_source(source) for source in selected_sources]
    confidence = _confidence_from_sources(ranked_sources)
    assumptions = _assumptions_from_inputs(selected_sources, simulation_kpis, intent_type)
    retrieval_context_count = len(ranked_sources)

    if not selected_sources:
        return SynthesisResponse(
            query=query,
            answer=(
                "Evidence is insufficient to answer the query from the indexed knowledge base. "
                "No useful retrieved source text was available for synthesis."
            ),
            confidence="low",
            citations=[],
            assumptions=assumptions,
            recommended_action=(
                "Ingest or retrieve more relevant runbook/specification context, then retry synthesis."
            ),
            used_simulation_kpis=simulation_kpis,
            intent_type=intent_type,
            retrieval_context_count=retrieval_context_count,
        )

    evidence_summary = _evidence_summary(query, selected_sources)
    kpi_summary = _kpi_summary(simulation_kpis)
    answer_parts = [
        f"Based on the retrieved context, the most relevant evidence points to: {evidence_summary}"
    ]
    if kpi_summary:
        answer_parts.append(f"Simulation KPIs provided for this decision are: {kpi_summary}.")
    answer_parts.append(
        "This synthesis is grounded only in the cited sources and avoids adding uncited standard clauses."
    )

    return SynthesisResponse(
        query=query,
        answer=" ".join(answer_parts),
        confidence=confidence,
        citations=citations,
        assumptions=assumptions,
        recommended_action=_recommended_action(query, selected_sources, simulation_kpis, intent_type),
        used_simulation_kpis=simulation_kpis,
        intent_type=intent_type,
        retrieval_context_count=retrieval_context_count,
    )


def _citation_from_source(source: SourceChunk) -> SynthesisCitation:
    return SynthesisCitation(
        source=source.source,
        title=source.title,
        section=source.section,
        chunk=source.chunk,
        page=source.page,
        kind=source.kind,
        source_type=source.source_type,
        score=source.score,
    )


def _confidence_from_sources(sources: list[SourceChunk]) -> str:
    if not sources:
        return "low"

    top_score = sources[0].score
    if top_score >= 0.75:
        return "high"
    if top_score >= 0.25:
        return "medium"
    return "low"


def _assumptions_from_inputs(
    selected_sources: list[SourceChunk],
    simulation_kpis: dict[str, Any] | None,
    intent_type: str | None,
) -> list[str]:
    assumptions = [
        "Retrieved chunks are treated as the authoritative evidence for this response.",
        "Citation scores are interpreted as retrieval relevance, not proof of root cause.",
    ]
    if simulation_kpis:
        assumptions.append("Simulation KPIs are caller-provided and have not been independently validated.")
    if intent_type:
        assumptions.append(f"Intent type was provided as {intent_type}.")
    if len(selected_sources) < 2:
        assumptions.append("Fewer than two useful sources were available, so confidence is constrained.")
    return assumptions


def _evidence_summary(query: str, sources: list[SourceChunk]) -> str:
    query_terms = _terms(query)
    summaries = []
    for index, source in enumerate(sources, start=1):
        snippet = _best_snippet(source.text, query_terms)
        summaries.append(f"[{index}] {source.title} ({source.section}) says {snippet}")
    return " ".join(summaries)


def _best_snippet(text: str, query_terms: set[str]) -> str:
    normalized = " ".join(text.split())
    sentences = [sentence.strip() for sentence in _SENTENCE_RE.split(normalized) if sentence.strip()]
    if not sentences:
        return _truncate(normalized)

    best_sentence = max(sentences, key=lambda sentence: _overlap_score(sentence, query_terms))
    if _overlap_score(best_sentence, query_terms) == 0:
        best_sentence = sentences[0]
    return _truncate(best_sentence)


def _terms(text: str) -> set[str]:
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "why",
    }
    return {token.lower() for token in _WORD_RE.findall(text) if token.lower() not in stop_words}


def _overlap_score(sentence: str, query_terms: set[str]) -> int:
    sentence_terms = _terms(sentence)
    return len(sentence_terms.intersection(query_terms))


def _truncate(text: str, limit: int = 260) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _kpi_summary(simulation_kpis: dict[str, Any] | None) -> str:
    if not simulation_kpis:
        return ""
    parts = [f"{key}={value}" for key, value in sorted(simulation_kpis.items())]
    return ", ".join(parts)


def _recommended_action(
    query: str,
    sources: list[SourceChunk],
    simulation_kpis: dict[str, Any] | None,
    intent_type: str | None,
) -> str:
    top_source = sources[0]
    action = (
        f"Review {top_source.title} ({top_source.section}) first and validate the retrieved guidance "
        "against current network measurements before applying changes."
    )
    lowered_query = query.lower()
    lowered_text = top_source.text.lower()
    if "handover" in lowered_query or "handover" in lowered_text:
        action = (
            "Check handover-related radio conditions, neighbor configuration, and mobility parameters "
            f"using {top_source.title} ({top_source.section}) as the cited starting point."
        )
    if simulation_kpis:
        action += " Compare the recommended checks with the supplied simulation KPIs before escalation."
    if intent_type and intent_type.upper() == "DIAGNOSTIC":
        action += " Treat this as a diagnostic lead rather than an automated remediation."
    return action
