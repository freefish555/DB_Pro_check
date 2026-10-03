"""Pure, local redaction for dynamic model request payloads.

This module deliberately has no transport, database, or logging side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


_PATTERNS = {
    "url": re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE),
    "ip": re.compile(r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])"),
    "phone": re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
    "landline": re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)"),
    "domain": re.compile(r"(?<![@\w])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?![\w-])", re.IGNORECASE),
    "identifier": re.compile(r"(?<![\w])(?:CERT|ID|NO)[-_:/A-Z0-9]{3,}(?![\w])", re.IGNORECASE),
}
_LABELED_PATTERNS = {
    "NAME": re.compile(r"(?:姓名|联系人|负责人|经办人)\s*[:：]\s*([\u4e00-\u9fff]{2,4})(?=[，。；;\s]|$)"),
    "ADDRESS": re.compile(r"(?:联系地址|通信地址|单位地址|住址|地址)\s*[:：]\s*([^\s，。；;]{4,80})"),
}
_CONTEXT_PATTERNS = (
    re.compile(r"(?<![\u4e00-\u9fff])(?:由|经)?([\u4e00-\u9fff]{2,4})(?=负责|担任|任职)"),
    re.compile(r"(?:位于|坐落于|地址为|地址是)([\u4e00-\u9fff0-9]{2,20}(?:省|市|区|县)[^\s，。；;]{2,50}?(?:路|街|巷|道)[^\s，。；;]{0,15}?号)"),
)
_UNCERTAIN = re.compile(r"(?<![\w])\d{3,}[-_/][A-Za-z][A-Za-z0-9_-]*(?![\w])")
_TOKEN = re.compile(r"^<[A-Z]+_\d{3}>$")
_TYPE_NAMES = {
    "name": "NAME", "names": "NAME", "person": "NAME", "people": "NAME",
    "organization": "ORG", "organisation": "ORG", "org": "ORG", "company": "ORG", "unit": "ORG",
    "phone": "PHONE", "phones": "PHONE", "telephone": "PHONE", "mobile": "PHONE",
    "address": "ADDRESS", "addresses": "ADDRESS", "location": "ADDRESS",
    "ip": "IP", "ips": "IP", "domain": "DOMAIN", "domains": "DOMAIN",
    "url": "URL", "urls": "URL", "identifier": "ID", "identifiers": "ID", "number": "ID", "numbers": "ID",
    "asset": "ASSET", "assets": "ASSET",
}

# A structured value carries stronger evidence than a free-text mention.  Keep
# these aliases deliberately narrow so internal ids and model contract fields
# (record_id, point_id, status, etc.) remain stable and locatable.
_STRUCTURED_FIELD_KINDS = {
    "name": "NAME", "fullname": "NAME", "personname": "NAME", "username": "NAME",
    "姓名": "NAME", "名称": "NAME", "人员": "NAME",
    "联系人": "NAME", "被测单位联系人": "NAME", "测评单位联系人": "NAME",
    "被测对象名称": "ASSET", "object": "ASSET", "asset": "ASSET",
    "被测单位名称": "ORG", "测评单位名称": "ORG",
    "organization": "ORG", "organisation": "ORG", "org": "ORG", "company": "ORG",
    "unit": "ORG", "department": "ORG", "enterprise": "ORG", "单位": "ORG", "组织": "ORG",
    "address": "ADDRESS", "location": "ADDRESS", "site": "ADDRESS", "postaladdress": "ADDRESS",
    "地址": "ADDRESS", "位置": "ADDRESS",
    "phone": "PHONE", "mobile": "PHONE", "telephone": "PHONE", "tel": "PHONE",
    "cellphone": "PHONE", "contactphone": "PHONE", "电话": "PHONE", "手机": "PHONE",
    "ip": "IP", "ipaddress": "IP", "ip地址": "IP",
    "domain": "DOMAIN", "域名": "DOMAIN",
    "url": "URL", "uri": "URL", "网址": "URL", "链接": "URL",
    "certificate": "ID", "cert": "ID", "identifier": "ID", "number": "ID",
    "编号": "ID", "证书": "ID", "证书号": "ID",
    "统一社会信用代码": "ID", "测评机构代码": "ID",
}

# These fields are plausibly sensitive but do not say whether the value is a
# person, organization, or location.  Replace them and hold the request for
# human confirmation rather than guessing a redaction class.
_UNCERTAIN_SENSITIVE_FIELDS = {
    "contact", "contacts", "person", "people", "owner", "applicant", "signer",
    "manager", "maintainer", "responsible", "responsibleperson", "operator",
    "联系人", "负责人", "责任人", "经办人", "维护人", "所有人",
    "等级测评结论",
}

_NON_SENSITIVE_VALUES = {"", "-", "--", "n/a", "na", "none", "null", "unknown", "无", "未知", "不适用", "未提供"}


def _field_key(value: Any) -> str:
    """Normalize a JSON field name without changing its displayed spelling."""
    return re.sub(r"[\s_.:/\\-]+", "", str(value or "").casefold())


def _structured_kind(key: Any) -> str | None:
    normalized = _field_key(key)
    if normalized in _STRUCTURED_FIELD_KINDS:
        return _STRUCTURED_FIELD_KINDS[normalized]
    # Support common compound keys such as contact_name while keeping the
    # explicit protected ids out of this suffix match.
    for suffix, kind in _STRUCTURED_FIELD_KINDS.items():
        suffix = _field_key(suffix)
        if suffix and normalized.endswith(suffix) and normalized not in {"recordid", "pointid", "requirementid"}:
            return kind
    return None


def _uncertain_field(key: Any) -> bool:
    return _field_key(key) in _UNCERTAIN_SENSITIVE_FIELDS


@dataclass(frozen=True)
class RedactedRequest:
    payload: Any
    token_map: dict[str, str]
    uncertain: list[str]
    hits: list[dict[str, str]]
    request_hash: str

    @property
    def suspicious(self) -> list[str]:
        return self.uncertain


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _token(kind: str, index: int) -> str:
    return f"<{kind}_{index:03d}>"


def _terms(project_terms: dict[str, Any]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for key, values in (project_terms or {}).items():
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple, set)):
            continue
        kind = _TYPE_NAMES.get(str(key).lower(), "TERM")
        for value in values:
            if isinstance(value, str) and value:
                found.append((value, kind, key))
    return sorted(found, key=lambda item: len(item[0]), reverse=True)


def _structured_terms(value: Any) -> list[tuple[str, str, str]]:
    """Reuse explicit sensitive field values wherever they recur in prose."""
    found: list[tuple[str, str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            kind = _structured_kind(key)
            if (kind and isinstance(item, str) and item.strip().casefold() not in _NON_SENSITIVE_VALUES
                    and not _TOKEN.fullmatch(item)):
                found.append((item, kind, str(key)))
            else:
                found.extend(_structured_terms(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_structured_terms(item))
    return found


def prepare_model_request(dynamic_payload: dict, project_terms: dict, token_map: dict, context: dict) -> RedactedRequest:
    """Return a fully redacted payload and a hash of payload plus model context."""
    required_context = {"prompt_version", "knowledge_version", "service_url", "model_config_version"}
    if not isinstance(dynamic_payload, dict) or not isinstance(context, dict) or not required_context.issubset(context):
        raise ValueError("dynamic payload and complete model context are required")
    mapping = dict(token_map or {})
    counters: dict[str, int] = {}
    used_tokens = set(mapping.values())
    terms = sorted(_terms(project_terms) + _structured_terms(dynamic_payload),
                   key=lambda item: len(item[0]), reverse=True)
    hits: list[dict[str, str]] = []
    uncertain: set[str] = set()

    def allocate(raw: str, kind: str) -> str:
        if raw in mapping:
            return mapping[raw]
        prefix = kind.upper()
        index = counters.get(prefix, 0) + 1
        while _token(prefix, index) in used_tokens:
            index += 1
        counters[prefix] = index
        mapping[raw] = _token(prefix, index)
        used_tokens.add(mapping[raw])
        return mapping[raw]

    def replace_text(value: str) -> str:
        spans: list[tuple[int, int, str, str]] = []
        for raw, kind, source in terms:
            start = 0
            while True:
                pos = value.find(raw, start)
                if pos < 0:
                    break
                spans.append((pos, pos + len(raw), raw, kind))
                start = pos + len(raw)
        for kind, pattern in _PATTERNS.items():
            for match in pattern.finditer(value):
                spans.append((match.start(), match.end(), match.group(0), kind.upper()))
        for kind, pattern in _LABELED_PATTERNS.items():
            for match in pattern.finditer(value):
                spans.append((match.start(1), match.end(1), match.group(1), kind))
        for pattern in _CONTEXT_PATTERNS:
            for match in pattern.finditer(value):
                spans.append((match.start(1), match.end(1), match.group(1), "REVIEW"))
        # Keep an unclassified identifier out of the request body while making
        # the request explicitly ineligible for automatic authorization.
        for match in _UNCERTAIN.finditer(value):
            spans.append((match.start(), match.end(), match.group(0), "REVIEW"))
        spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
        chosen: list[tuple[int, int, str, str]] = []
        end = -1
        for span in spans:
            if span[0] >= end:
                chosen.append(span)
                end = span[1]
        out: list[str] = []
        cursor = 0
        for start, finish, raw, kind in chosen:
            out.append(value[cursor:start])
            replacement = allocate(raw, kind)
            out.append(replacement)
            hits.append({"type": kind.lower(), "token": replacement})
            if kind == "REVIEW":
                uncertain.add(replacement)
            cursor = finish
        out.append(value[cursor:])
        redacted = "".join(out)
        return redacted

    def replace_structured(value: str, kind: str, requires_review: bool = False) -> str:
        """Replace a sensitive structured leaf even when no project term exists."""
        if value.strip().casefold() in _NON_SENSITIVE_VALUES or _TOKEN.fullmatch(value):
            return value
        replacement = allocate(value, "REVIEW" if requires_review else kind)
        hits.append({"type": ("review" if requires_review else kind).lower(), "token": replacement})
        if requires_review:
            uncertain.add(replacement)
        return replacement

    def walk(value: Any, field_kind: str | None = None, requires_review: bool = False) -> Any:
        if isinstance(value, str):
            if field_kind or requires_review:
                return replace_structured(value, field_kind or "REVIEW", requires_review)
            return replace_text(value)
        if isinstance(value, list):
            return [walk(item, field_kind, requires_review) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                kind = _structured_kind(key)
                review = _uncertain_field(key)
                safe_key = key if kind or review or not isinstance(key, str) else replace_text(key)
                result[safe_key] = walk(item, kind, review)
            return result
        return value

    redacted_payload = walk(dynamic_payload)
    def values(value: Any):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from values(item)
        elif isinstance(value, list):
            for item in value:
                yield from values(item)

    # A raw term left in a value is a hard failure. Schema field names can
    # contain ordinary words that happen to equal a short sensitive value.
    for raw in mapping:
        if raw and any(raw in value for value in values(redacted_payload)):
            raise ValueError("redaction final scan failed")
    digest_input = {"payload": redacted_payload, "context": context}
    request_hash = hashlib.sha256(_canonical(digest_input).encode("utf-8")).hexdigest()
    return RedactedRequest(redacted_payload, mapping, sorted(uncertain), hits, request_hash)


def assert_authorized(*args: Any) -> None:
    """Raise unless an approved hash matches the current request hash.

    Accepts ``(approved_hash, current_hash)`` or ``(run_id, record_id,
    current_hash, approved_hash)`` for callers that keep authorization state.
    """
    if len(args) == 2:
        approved, current = args
    elif len(args) == 3:
        _, approved, current = args
    elif len(args) == 4:
        _, _, current, approved = args
    else:
        raise TypeError("assert_authorized expects approved/current hashes")
    if not approved or approved != current:
        raise ValueError("redaction approval missing or stale")
