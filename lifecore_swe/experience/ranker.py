from pathlib import Path
"""Deterministic ranking and selection reasoning for candidate experiences."""

import re
from typing import Dict, List, Set, Tuple
from .models import ExperienceRecord, VerificationStatus


class ExperienceRanker:
    """Ranks experience candidates using deterministic multi-signal scoring."""

    @staticmethod
    def _tokenize(text: str) -> Set[str]:
        """Extract alphanumeric word tokens of length >= 3."""
        return set(re.findall(r"\b[a-zA-Z0-9_]{3,}\b", text.lower()))

    def score(
        self,
        candidate: ExperienceRecord,
        query_text: str,
        target_repository: str,
        target_version: str,
        graph_files: List[str],
        graph_symbols: List[str],
    ) -> Tuple[float, List[str]]:
        """Calculate relevance score in [0.0, 1.0] and generate explanation reasons."""
        reasons: List[str] = []

        # 1. Repository match (Weight: 0.25)
        repo_score = 0.0
        if candidate.repository_id == target_repository:
            repo_score = 1.0
            reasons.append(f"Repository match: '{target_repository}'")
        else:
            reasons.append(f"Cross-repository: '{candidate.repository_id}' vs '{target_repository}'")

        # 2. File overlap (Weight: 0.35)
        candidate_files = set(f.lower() for f in (candidate.files_modified + candidate.files_inspected))
        target_files_set = set(f.lower() for f in graph_files)
        common_files = candidate_files.intersection(target_files_set)
        file_score = 0.0
        if target_files_set and common_files:
            file_score = len(common_files) / max(len(target_files_set), 1)
            reasons.append(f"Overlapping files ({len(common_files)}): {list(common_files)[:3]}")
        elif not target_files_set and candidate.files_modified:
            # Check if any candidate file is mentioned in query text
            q_lower = query_text.lower()
            matched_in_q = [f for f in candidate.files_modified if f.lower() in q_lower or Path(f).name.lower() in q_lower]
            if matched_in_q:
                file_score = 0.8
                reasons.append(f"Candidate file mentioned in task query: {matched_in_q[:2]}")

        # 3. Symbol overlap (Weight: 0.20)
        candidate_symbols = set(s.lower() for s in (candidate.symbols_modified + candidate.relevant_nodes))
        target_sym_set = set(s.lower() for s in graph_symbols)
        common_symbols = candidate_symbols.intersection(target_sym_set)
        symbol_score = 0.0
        if target_sym_set and common_symbols:
            symbol_score = len(common_symbols) / max(len(target_sym_set), 1)
            reasons.append(f"Overlapping symbols: {list(common_symbols)[:3]}")
        elif not target_sym_set:
            q_lower = query_text.lower()
            matched_sym = [s for s in candidate_symbols if s in q_lower]
            if matched_sym:
                symbol_score = 0.7
                reasons.append(f"Candidate symbol mentioned in task: {matched_sym[:2]}")

        # 4. Text signal overlap (Weight: 0.20)
        q_tokens = self._tokenize(query_text)
        exp_text = f"{candidate.task_description} {candidate.hypothesis} {candidate.patch_summary}"
        exp_tokens = self._tokenize(exp_text)
        common_tokens = q_tokens.intersection(exp_tokens)
        text_score = 0.0
        if q_tokens and common_tokens:
            text_score = min(len(common_tokens) / max(len(q_tokens), 1), 1.0)
            reasons.append(f"Task keywords matched ({len(common_tokens)}): {list(common_tokens)[:4]}")

        # Verification status multiplier
        status_mult = 1.0
        if candidate.verification_status == VerificationStatus.VERIFIED.value:
            status_mult = 1.0
            reasons.append(f"Verified solution status on task '{candidate.task_id}'")
        elif candidate.verification_status == VerificationStatus.TESTED.value:
            status_mult = 0.6
            reasons.append("Unverified testing status")
        elif candidate.verification_status == VerificationStatus.FAILED.value:
            status_mult = 0.5
            reasons.append(f"Failure trajectory: {candidate.failure_reason or 'Tests failed'}")
        else:
            status_mult = 0.3

        raw_score = (
            0.25 * repo_score +
            0.35 * file_score +
            0.20 * symbol_score +
            0.20 * text_score
        ) * status_mult

        final_score = round(min(max(raw_score, 0.0), 1.0), 4)
        return final_score, reasons

    def rank(
        self,
        candidates: List[ExperienceRecord],
        query_text: str,
        target_repository: str,
        target_version: str,
        graph_files: List[str],
        graph_symbols: List[str],
        min_score: float = 0.05,
    ) -> List[Tuple[ExperienceRecord, float, List[str]]]:
        """Rank candidate experiences in descending score order."""
        scored = []
        for cand in candidates:
            score_val, reasons = self.score(
                candidate=cand,
                query_text=query_text,
                target_repository=target_repository,
                target_version=target_version,
                graph_files=graph_files,
                graph_symbols=graph_symbols,
            )
            if score_val >= min_score:
                scored.append((cand, score_val, reasons))

        # Deterministic sort: score desc, then timestamp desc, then experience_id asc
        scored.sort(key=lambda x: (x[1], x[0].timestamp, x[0].experience_id), reverse=True)
        return scored
