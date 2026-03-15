from __future__ import annotations

from difflib import SequenceMatcher

from app.schemas.shared import Belief, BeliefDiff, DiffLine


def compute_belief_diff(before: Belief, after: Belief, reinterpreted_ids: list[str]) -> BeliefDiff:
    before_lines = before.answer_text.splitlines()
    after_lines = after.answer_text.splitlines()

    matcher = SequenceMatcher(a=before_lines, b=after_lines)
    diff_lines: list[DiffLine] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            diff_lines.extend(DiffLine(type="unchanged", text=line) for line in before_lines[i1:i2])
        elif tag == "delete":
            diff_lines.extend(DiffLine(type="removed", text=line) for line in before_lines[i1:i2])
        elif tag == "insert":
            diff_lines.extend(DiffLine(type="added", text=line) for line in after_lines[j1:j2])
        elif tag == "replace":
            diff_lines.extend(DiffLine(type="removed", text=line) for line in before_lines[i1:i2])
            diff_lines.extend(DiffLine(type="added", text=line) for line in after_lines[j1:j2])

    new_evidence_ids = sorted(list(set(after.evidence_report_ids) - set(before.evidence_report_ids)))

    return BeliefDiff(
        before=before,
        after=after,
        text_diff=diff_lines,
        confidence_delta=after.confidence_score - before.confidence_score,
        new_evidence_ids=new_evidence_ids,
        reinterpreted_report_ids=reinterpreted_ids,
        triggered_by_quarter=after.quarter_context,
    )
