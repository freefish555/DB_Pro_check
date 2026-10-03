import json

import pytest

from backend.redaction import (
    RedactedRequest,
    assert_authorized,
    prepare_model_request,
)


TERMS = {
    "name": ["张三"],
    "organization": ["合成科技有限公司"],
    "address": ["北京市朝阳区测试路1号"],
}


def test_unknown_prose_identity_is_masked_and_blocked_until_added_to_dictionary():
    context = {'prompt_version': 'v1', 'knowledge_version': 'v1',
               'service_url': 'http://localhost', 'model_config_version': 'v1'}
    prose = {'text': '张三负责运维。机房位于上海市浦东新区测试路88号。'}
    unknown = prepare_model_request(prose, {}, {}, context)
    assert '张三' not in unknown.payload['text']
    assert '上海市浦东新区测试路88号' not in unknown.payload['text']
    assert unknown.uncertain
    known = prepare_model_request(prose, {'name': ['张三'],
        'address': ['上海市浦东新区测试路88号']}, {}, context)
    assert not known.uncertain


def payload():
    return {
        "record": {
            "name": "张三",
            "organization": "合成科技有限公司",
            "phone": "13812345678",
            "address": "北京市朝阳区测试路1号",
            "ip": "192.0.2.10",
            "domain": "example.test",
            "url": "https://example.test:8443/a/b",
            "certificate": "CERT-2026-0001",
        },
        "nested": [{"text": "由张三负责，访问 https://example.test/a"}],
    }


def test_all_dynamic_fields_are_redacted_and_serialized_payload_has_no_raw_values():
    result = prepare_model_request(payload(), TERMS, {}, {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"})

    assert isinstance(result, RedactedRequest)
    encoded = json.dumps(result.payload, ensure_ascii=False)
    for raw in ("张三", "合成科技有限公司", "13812345678", "北京市朝阳区测试路1号", "192.0.2.10", "example.test", "https://example.test:8443/a/b", "CERT-2026-0001"):
        assert raw not in encoded
    assert result.hits
    assert not result.uncertain


def test_same_value_gets_stable_token_across_batch():
    context = {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"}
    first = prepare_model_request(payload(), TERMS, {}, context)
    second = prepare_model_request({"other": "张三"}, TERMS, first.token_map, context)

    assert second.token_map["张三"] == first.token_map["张三"]
    assert second.payload["other"] == first.payload["record"]["name"]


def test_changed_context_invalidates_hash():
    context = {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"}
    first = prepare_model_request(payload(), TERMS, {}, context)
    changed = prepare_model_request(payload(), TERMS, {}, {**context, "prompt_version": "p2"})

    assert first.request_hash != changed.request_hash
    with pytest.raises(ValueError):
        assert_authorized(changed.request_hash, first.request_hash)


def test_uncertain_request_is_not_authorized():
    result = prepare_model_request({"text": "contact 123-unknown"}, {}, {}, {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"})

    assert result.uncertain
    with pytest.raises(ValueError):
        assert_authorized(result.request_hash, None)


def test_complete_appendix_dynamic_object_is_redacted_before_model_request():
    from backend.app import appendix_dynamic_payload

    record = {"id": "r-1", "source": "张三 / 合成科技有限公司", "object": "北京测试单位",
              "text": "联系 13812345678，访问 https://example.test/a", "verdict": "符合", "control": "C-2026"}
    requirement = {"key": "q-1", "source": "核查点来源", "text": "核查北京测试单位",
                   "decision": "满足条件", "points": [{"id": "p1", "text": "地址"}]}
    terms = {**TERMS, "address": ["�����г���������·1��", "�������Ե�λ"]}
    result = prepare_model_request(appendix_dynamic_payload(record, requirement), terms, {},
        {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"})
    serialized = json.dumps(result.payload, ensure_ascii=False)
    for raw in ("张三", "合成科技有限公司", "13812345678", "https://example.test/a"):
        assert raw not in serialized
    assert result.payload["record"]["id"] == "r-1"
    assert result.payload["requirement"]["points"][0]["id"] == "p1"


def test_structured_sensitive_fields_are_redacted_without_project_terms():
    context = {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"}
    value = {
        "record": {
            "name": "李四",
            "organization": "北方电力研究院",
            "address": "上海市浦东新区测试路88号",
            "phone": "13912345678",
            "ip_address": "198.51.100.42",
            "url": "https://internal.example.test/report",
        },
        "requirement": {"text": "核查对象", "points": [{"id": "p1", "text": "核查"}]},
    }

    result = prepare_model_request(value, {}, {}, context)
    encoded = json.dumps(result.payload, ensure_ascii=False)
    for raw in ("李四", "北方电力研究院", "上海市浦东新区测试路88号", "13912345678", "198.51.100.42", "https://internal.example.test/report"):
        assert raw not in encoded
    assert not result.uncertain
    assert result.payload["requirement"]["points"][0]["id"] == "p1"


def test_ambiguous_contact_field_is_redacted_but_requires_confirmation():
    context = {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"}
    result = prepare_model_request({"record": {"contact": "王五", "record_id": "r-1"}}, {}, {}, context)

    encoded = json.dumps(result.payload, ensure_ascii=False)
    assert "王五" not in encoded
    assert result.uncertain
    assert result.payload["record"]["record_id"] == "r-1"
    with pytest.raises(ValueError):
        assert_authorized(result.request_hash, None)


def test_uploaded_field_list_aliases_and_repeated_names_are_redacted_without_terms():
    context = {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"}
    value = {
        "被测单位联系人": "张三",
        "统一社会信用代码": "91310115MA1K999999",
        "被测对象名称": "合成调度系统",
        "等级测评结论": "合成调度系统由张三负责。",
    }
    result = prepare_model_request(value, {}, {}, context)
    encoded = json.dumps(result.payload, ensure_ascii=False)
    for raw in ("张三", "91310115MA1K999999", "合成调度系统"):
        assert raw not in encoded


def test_labeled_person_and_contact_address_in_free_text_are_hidden():
    context = {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"}
    text = "联系人：王五，电话：010-12345678，联系地址：北京市朝阳区测试路12号。"
    result = prepare_model_request({"text": text}, {}, {}, context)
    encoded = json.dumps(result.payload, ensure_ascii=False)
    for raw in ("王五", "010-12345678", "北京市朝阳区测试路12号"):
        assert raw not in encoded


def test_sensitive_value_repeated_in_field_label_does_not_fail_final_scan():
    context = {"prompt_version": "p1", "knowledge_version": "k1", "service_url": "https://model.test", "model_config_version": "m1"}
    result = prepare_model_request({"被测单位名称": "单位"}, {}, {}, context)
    assert result.payload["被测单位名称"].startswith("<ORG_")
