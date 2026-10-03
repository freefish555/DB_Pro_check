import json

import httpx
import pytest

from backend.ai import evaluate
from backend.redaction import prepare_model_request


def _inputs():
    record = {"id": "r1", "text": "已实施访问控制，结论符合。", "verdict": "符合"}
    requirement = {
        "text": "访问控制",
        "decision": "已实施访问控制为符合",
        "points": [{"id": "p1", "text": "实施访问控制"}],
    }
    return record, requirement


@pytest.mark.parametrize("mode", ["lenient", "strict"])
def test_model_request_contains_complete_analysis_contract_and_mode(monkeypatch, mode):
    record, requirement = _inputs()
    seen = []
    answer = {
        "record_id": "r1",
        "semantic_alignment": {"status": "aligned", "reason": "语义一致"},
        "point_results": [{"point_id": "p1", "coverage": "covered", "evidence_quote": "访问控制", "reason": "已描述"}],
        "key_condition_missing": {"status": "no", "point_ids": [], "reason": "没有缺失"},
        "verdict_review": {"status": "supported", "evidence_quote": "结论符合", "reason": "一致"},
        "writing": [],
    }

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]})

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    value = evaluate(record, requirement, mode, {"base_url": "http://127.0.0.1/v1", "model": "test"}, "")
    assert value["record_id"] == "r1"
    prompt = json.loads(seen[0]["messages"][1]["content"])
    assert set(prompt["输出结构"]) == {
        "record_id", "semantic_alignment", "point_results", "key_condition_missing", "verdict_review", "writing"
    }
    assert ("基本一致" if mode == "lenient" else "全覆盖") in prompt["审核口径"]
    assert "错别字" in prompt["审核口径"] and "符合情况" in prompt["审核口径"]


def test_model_transport_rejects_unredacted_dynamic_values(monkeypatch):
    record, requirement = _inputs()
    record["text"] = "联系人张三，电话13812345678。"
    record["object"] = "测试设备"
    sent = []
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: (sent.append(True), original(**kwargs))[1])
    with pytest.raises(ValueError, match="脱敏"):
        evaluate(record, requirement, "lenient", {"base_url": "http://127.0.0.1/v1", "model": "test"}, "")
    assert not sent


def test_approved_redacted_payload_passes_egress_check(monkeypatch):
    record, requirement = _inputs()
    record["object"] = "合成系统"
    record["text"] = "合成系统已实施访问控制，结论符合。"
    context = {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "http://127.0.0.1/v1", "model_config_version": "m1"}
    prepared = prepare_model_request({"record": record, "requirement": requirement}, {}, {}, context)
    redacted_record = prepared.payload["record"]
    answer = {
        "record_id": "r1",
        "semantic_alignment": {"status": "aligned"},
        "point_results": [{"point_id": "p1", "coverage": "covered", "evidence_quote": "访问控制"}],
        "key_condition_missing": {"status": "no", "point_ids": []},
        "verdict_review": {"status": "supported", "evidence_quote": "结论符合"},
        "writing": [],
    }
    original = httpx.Client
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]}))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))
    assert evaluate(redacted_record, prepared.payload["requirement"], "strict",
                    {"base_url": "http://127.0.0.1/v1", "model": "test"}, "")["record_id"] == "r1"
