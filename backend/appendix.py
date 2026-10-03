"""Deterministic classification of structured Appendix D model output.

The model is treated as an evidence-producing parser.  This module validates its
shape and source quotes first, then derives the J-N issue columns without using
free text as a conclusion.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


MODES = {"regular", "lenient", "strict"}
ALIGNMENTS = {"aligned", "partial", "unrelated", "unknown"}
COVERAGE = {"covered", "missing", "unclear"}
KEY_CONDITION = {"yes", "no", "unknown"}
VERDICTS = {"supported", "contradicted", "unknown"}
WRITING_TYPES = {"typo", "grammar"}
COLUMNS = ("J", "K", "L", "M", "N")


class AnalysisValidationError(ValueError):
    """Raised when a model analysis cannot be trusted as evidence."""


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _obj(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise AnalysisValidationError(f"{name} must be an object")
    return value


def _status(value: Any, allowed: set[str], name: str) -> str:
    status = _obj(value, name).get("status")
    if status not in allowed:
        raise AnalysisValidationError(f"invalid {name} status")
    return status


def _quote(value: Any, record_text: str, name: str, *, required: bool = False) -> str:
    quote = value.get("evidence_quote", "") if isinstance(value, dict) else ""
    if not isinstance(quote, str):
        raise AnalysisValidationError(f"invalid {name} evidence quote")
    if required and not quote:
        raise AnalysisValidationError(f"missing {name} evidence quote")
    if quote and quote not in record_text:
        raise AnalysisValidationError(f"{name} evidence quote is not in record")
    return quote


def validate_analysis(record: dict, requirement: dict, analysis: dict) -> dict:
    """Validate and return a normalized analysis.

    Validation is intentionally independent from the classification policy.  A
    valid ``missing`` result may have an empty quote, while a positive or
    contradictory claim must point to text in the record.
    """
    if not isinstance(record, dict) or not isinstance(requirement, dict):
        raise AnalysisValidationError("record and requirement must be objects")
    if not isinstance(analysis, dict):
        raise AnalysisValidationError("analysis must be an object")
    record_id = record.get("id")
    if not isinstance(record_id, str) or not record_id or analysis.get("record_id") != record_id:
        raise AnalysisValidationError("record_id does not match record")
    record_text = _text(record.get("text"))
    points = requirement.get("points")
    if not isinstance(points, list) or not points:
        raise AnalysisValidationError("requirement has no points")
    point_ids = []
    for point in points:
        point = _obj(point, "requirement point")
        point_id = point.get("id")
        if not isinstance(point_id, str) or not point_id:
            raise AnalysisValidationError("requirement point has no id")
        point_ids.append(point_id)
    if len(set(point_ids)) != len(point_ids):
        raise AnalysisValidationError("requirement has duplicate point ids")
    if not isinstance(requirement.get("decision"), str) or not requirement.get("decision").strip():
        raise AnalysisValidationError("requirement has no decision rule")

    alignment = _obj(analysis.get("semantic_alignment"), "semantic_alignment")
    alignment_status = _status(alignment, ALIGNMENTS, "semantic_alignment")
    point_results = analysis.get("point_results")
    if not isinstance(point_results, list):
        raise AnalysisValidationError("point_results must be a list")
    observed_ids = [item.get("point_id") if isinstance(item, dict) else None for item in point_results]
    if len(point_results) != len(point_ids) or set(observed_ids) != set(point_ids):
        raise AnalysisValidationError("point_results must contain every point exactly once")
    if any(count != 1 for count in Counter(observed_ids).values()):
        raise AnalysisValidationError("point_results contains duplicate point")
    normalized_points = []
    for item in point_results:
        item = _obj(item, "point result")
        status = item.get("coverage")
        if status not in COVERAGE:
            raise AnalysisValidationError("invalid point coverage")
        quote = _quote(item, record_text, "point", required=status == "covered")
        if status == "missing" and quote:
            raise AnalysisValidationError("missing point cannot cite evidence")
        normalized_points.append({**item, "evidence_quote": quote})

    missing = _obj(analysis.get("key_condition_missing"), "key_condition_missing")
    missing_status = _status(missing, KEY_CONDITION, "key_condition_missing")
    point_set = set(point_ids)
    missing_ids = missing.get("point_ids", [])
    if not isinstance(missing_ids, list) or any(point_id not in point_set for point_id in missing_ids):
        raise AnalysisValidationError("key_condition_missing has invalid point ids")
    if len(set(missing_ids)) != len(missing_ids):
        raise AnalysisValidationError("key_condition_missing has duplicate point ids")

    verdict = _obj(analysis.get("verdict_review"), "verdict_review")
    verdict_status = _status(verdict, VERDICTS, "verdict_review")
    _quote(verdict, record_text, "verdict", required=verdict_status in {"supported", "contradicted"})

    writing = analysis.get("writing", [])
    if not isinstance(writing, list):
        raise AnalysisValidationError("writing must be a list")
    normalized_writing = []
    for item in writing:
        item = _obj(item, "writing item")
        if item.get("type") not in WRITING_TYPES:
            raise AnalysisValidationError("invalid writing type")
        quote = _quote(item, record_text, "writing", required=True)
        suggestion = item.get("suggestion")
        if not isinstance(suggestion, str) or not suggestion.strip():
            raise AnalysisValidationError("writing suggestion is empty")
        normalized_writing.append({**item, "evidence_quote": quote})

    return {
        **analysis,
        "semantic_alignment": {**alignment, "status": alignment_status},
        "point_results": normalized_points,
        "key_condition_missing": {**missing, "status": missing_status, "point_ids": list(missing_ids)},
        "verdict_review": {**verdict, "status": verdict_status},
        "writing": normalized_writing,
    }


def _issue(code: str, column: str, reason: str = "", **extra: Any) -> dict:
    value = {"code": code, "column": column}
    if reason:
        value["reason"] = reason
    value.update({key: value for key, value in extra.items() if value is not None})
    return value


def _pending(record_id: Any, mode: str, reason: str) -> dict:
    issue = _issue("analysis_invalid", "", reason)
    columns = {column: [] for column in COLUMNS}
    return {
        "record_id": record_id,
        "mode": mode,
        "issues": [issue],
        "has_issue": True,
        "review_state": "pending",
        "columns": columns,
    }


def classify_appendix(record: dict, requirement: dict, analysis: dict, mode: str) -> dict:
    """Classify one result record into deterministic J-N issue columns.

    ``regular`` is the user-facing name for the historical ``lenient`` mode.
    Validation failures and uncertain model states remain ``pending``; they are
    never represented as a clean result.
    """
    if mode not in MODES:
        raise ValueError("invalid appendix review mode")
    public_mode = "regular" if mode == "lenient" else mode
    try:
        value = validate_analysis(record, requirement, analysis)
    except (AnalysisValidationError, TypeError, AttributeError) as exc:
        return _pending(record.get("id") if isinstance(record, dict) else None, public_mode, str(exc))

    columns = {column: [] for column in COLUMNS}
    issues = []
    record_id = record["id"]
    alignment = value["semantic_alignment"]["status"]
    unrelated = alignment == "unrelated"
    if unrelated:
        item = _issue("unrelated", "K", value["semantic_alignment"].get("reason", ""),
                      record_id=record_id)
        columns["K"].append(item); issues.append(item)
    elif alignment == "unknown":
        issues.append(_issue("alignment_unknown", "", value["semantic_alignment"].get("reason", "")))

    verdict = value["verdict_review"]
    if verdict["status"] == "contradicted":
        item = _issue("contradicted", "J", verdict.get("reason", ""),
                      record_id=record_id, evidence_quote=verdict.get("evidence_quote", ""))
        columns["J"].append(item); issues.append(item)
    elif verdict["status"] == "unknown":
        issues.append(_issue("verdict_unknown", "", verdict.get("reason", "")))

    key_missing = value["key_condition_missing"]
    if key_missing["status"] == "yes" and not unrelated:
        for point_id in key_missing["point_ids"]:
            item = _issue("key_condition_missing", "N", key_missing.get("reason", ""),
                          record_id=record_id, point_id=point_id)
            columns["N"].append(item); issues.append(item)
    elif key_missing["status"] == "unknown":
        issues.append(_issue("key_condition_unknown", "", key_missing.get("reason", "")))

    for point in value["point_results"]:
        if (point["coverage"] == "missing" and public_mode == "strict" and not unrelated
                and point["point_id"] not in key_missing["point_ids"]):
            item = _issue("point_missing", "N", point.get("reason", ""),
                          record_id=record_id, point_id=point["point_id"])
            columns["N"].append(item); issues.append(item)
        elif point["coverage"] == "unclear":
            issues.append(_issue("point_unclear", "", point.get("reason", ""),
                                 record_id=record_id, point_id=point["point_id"]))

    for writing in value["writing"]:
        column = "M" if writing["type"] == "typo" else "L"
        item = _issue(writing["type"], column, writing.get("suggestion", ""),
                      record_id=record_id, evidence_quote=writing["evidence_quote"],
                      suggestion=writing["suggestion"])
        columns[column].append(item); issues.append(item)

    pending_codes = {"alignment_unknown", "verdict_unknown", "key_condition_unknown", "point_unclear"}
    pending = any(item["code"] in pending_codes for item in issues)
    state = "pending" if pending else "ready"
    return {
        "record_id": record_id,
        "mode": public_mode,
        "issues": issues,
        "has_issue": bool(issues),
        "review_state": state,
        "columns": columns,
    }
