import copy

import pytest

from backend.appendix import classify_appendix


def record(text="记录描述了访问控制和日志留存，结论为符合。", verdict="符合"):
    return {"id": "r1", "text": text, "verdict": verdict, "object": "合成对象"}


def requirement(decision="应启用访问控制并保留日志"):
    return {
        "key": "req-1",
        "text": "访问控制与日志",
        "decision": decision,
        "points": [
            {"id": "p1", "text": "启用访问控制"},
            {"id": "p2", "text": "保留日志"},
        ],
    }


def analysis(**changes):
    value = {
        "record_id": "r1",
        "semantic_alignment": {"status": "aligned", "reason": "有相关描述"},
        "point_results": [
            {"point_id": "p1", "coverage": "covered", "evidence_quote": "访问控制", "reason": "已描述"},
            {"point_id": "p2", "coverage": "covered", "evidence_quote": "日志留存", "reason": "已描述"},
        ],
        "key_condition_missing": {"status": "no", "point_ids": [], "reason": "关键条件已有依据"},
        "verdict_review": {"status": "supported", "evidence_quote": "符合", "reason": "记录支持结论"},
        "writing": [],
    }
    value.update(changes)
    return value


def test_regular_allows_noncritical_omission_strict_reports_n():
    result = analysis(
        point_results=[
            {"point_id": "p1", "coverage": "covered", "evidence_quote": "访问控制", "reason": "已描述"},
            {"point_id": "p2", "coverage": "missing", "evidence_quote": "", "reason": "未逐项描述"},
        ]
    )
    regular = classify_appendix(record(), requirement(), result, "regular")
    strict = classify_appendix(record(), requirement(), result, "strict")
    assert regular["review_state"] == "ready"
    assert regular["columns"]["N"] == []
    assert strict["columns"]["N"]
    assert strict["columns"]["N"][0]["point_id"] == "p2"


def test_unrelated_goes_k_without_duplicate_n():
    value = analysis(
        semantic_alignment={"status": "unrelated", "reason": "记录与核查点无关"},
        point_results=[
            {"point_id": "p1", "coverage": "missing", "evidence_quote": "", "reason": "无相关描述"},
            {"point_id": "p2", "coverage": "missing", "evidence_quote": "", "reason": "无相关描述"},
        ],
        key_condition_missing={"status": "yes", "point_ids": ["p1", "p2"], "reason": "没有描述"},
    )
    result = classify_appendix(record(), requirement(), value, "strict")
    assert result["columns"]["K"]
    assert result["columns"]["N"] == []


def test_key_condition_goes_n_in_both_modes():
    value = analysis(
        key_condition_missing={"status": "yes", "point_ids": ["p1"], "reason": "关键条件未出现"}
    )
    for mode in ("regular", "strict"):
        result = classify_appendix(record(), requirement(), value, mode)
        assert result["columns"]["N"]
        assert result["columns"]["N"][0]["code"] == "key_condition_missing"


def test_strict_missing_key_point_is_reported_once():
    value = analysis(
        point_results=[
            {"point_id": "p1", "coverage": "missing", "evidence_quote": ""},
            {"point_id": "p2", "coverage": "covered", "evidence_quote": "日志留存"},
        ],
        key_condition_missing={"status": "yes", "point_ids": ["p1"]},
    )
    result = classify_appendix(record(), requirement(), value, "strict")
    assert len(result["columns"]["N"]) == 1


def test_verdict_typo_grammar_same_in_both_modes():
    value = analysis(
        verdict_review={"status": "contradicted", "evidence_quote": "符合", "reason": "结论与记录不一致"},
        writing=[
            {"type": "typo", "evidence_quote": "访问控制", "suggestion": "访问控制措施"},
            {"type": "grammar", "evidence_quote": "日志留存", "suggestion": "应保留日志"},
        ],
    )
    for mode in ("regular", "strict"):
        result = classify_appendix(record(), requirement(), value, mode)
        assert result["columns"]["J"]
        assert result["columns"]["L"]
        assert result["columns"]["M"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x["point_results"].__setitem__(0, {**x["point_results"][0], "coverage": "maybe"}),
        lambda x: x["point_results"].append(copy.deepcopy(x["point_results"][0])),
        lambda x: x["point_results"].__setitem__(0, {**x["point_results"][0], "evidence_quote": "文档中没有这句话"}),
    ],
)
def test_invalid_enum_duplicate_point_fabricated_quote_is_pending(mutate):
    value = analysis()
    mutate(value)
    result = classify_appendix(record(), requirement(), value, "strict")
    assert result["review_state"] == "pending"
    assert result["has_issue"]


def test_no_rule_never_becomes_supported():
    value = analysis(verdict_review={"status": "supported", "evidence_quote": "符合", "reason": "看起来通过"})
    result = classify_appendix(record(), requirement(decision=""), value, "regular")
    assert result["review_state"] == "pending"
    assert result["has_issue"]
    assert result["columns"]["J"] == []
