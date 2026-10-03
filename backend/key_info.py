"""Source-preserving identity fields and inventory row counts for three DOCX roles."""

import re
from collections import Counter

from .consistency_mapping import MAPPING, _field_header_map, _header_row, _key, _row_cells, locate_tables


ROLES = ('survey', 'plan', 'report')
SCOPES = ('full', 'sample')
FIELD_SPECS = (
    ('system_name', '系统/对象名称', '对象信息', ('系统名称', '等级保护对象名称', '定级对象名称', '被测对象名称', '网络名称')),
    ('protection_level', '保护等级', '对象信息', ('安全保护等级', '安全保护等级（SxAx）', '保护等级', '定级等级', '等级')),
    ('filing_number', '备案编号', '对象信息', ('备案编号', '备案证明编号', '备案号')),
    ('system_form', '定级对象形态', '对象信息', ('定级对象形态', '对象形态')),
    ('tested_name', '被测单位名称', '被测单位', ('被测单位名称', '被测单位全称', '单位全称', '单位名称', '被测单位')),
    ('tested_address', '被测单位地址', '被测单位', ('被测单位地址', '单位地址', '地址')),
    ('tested_postcode', '被测单位邮编', '被测单位', ('邮政编码', '邮编')),
    ('tested_leader', '负责人', '被测单位', ('负责人姓名', '单位负责人', '负责人')),
    ('tested_leader_phone', '负责人电话', '被测单位', ('负责人电话',)),
    ('tested_contact', '被测单位联系人', '被测单位', ('被测单位联系人', '联系人姓名', '项目联系人', '联系人')),
    ('tested_phone', '被测单位联系电话', '被测单位', ('被测单位联系电话', '联系人电话', '办公电话', '移动电话', '联系电话', '电话', '手机')),
    ('assessor_name', '测评单位名称', '测评单位', ('测评单位名称', '测评单位全称', '单位名称', '编制单位', '测评单位')),
    ('assessor_address', '测评单位地址', '测评单位', ('测评单位地址', '单位地址', '地址')),
    ('assessor_contact', '测评单位联系人', '测评单位', ('测评单位联系人', '联系人姓名', '联系人')),
    ('assessor_phone', '测评单位联系电话', '测评单位', ('测评单位联系电话', '联系人电话', '办公电话', '移动电话', '联系电话', '电话', '手机')),
    ('author', '编制人', '测评单位', ('编制人', '编写人')),
    ('reviewer', '审阅人', '测评单位', ('审阅人', '审核人')),
    ('approver', '批准人', '测评单位', ('批准人',)),
    ('credit_code', '统一社会信用代码', '单位代码', ('统一社会信用代码',)),
    ('organization_code', '机构代码', '单位代码', ('机构代码',)),
    ('extension_application', '扩展要求应用情况', '适用依据', ('扩展要求应用情况', '扩展应用情况', '扩展要求')),
    ('industry_application', '行业标准应用情况', '适用依据', ('行业标准应用情况', '行标应用情况')),
    ('conclusion', '测评结论', '报告结论', ('测评结论', '等级测评结论（公章或专用章）')),
    ('major_hazard_count', '重大隐患数量', '报告结论', ('重大隐患数量', '重大风险隐患数量')),
)
ALIASES = {field_id: {_key(a) for a in aliases} for field_id, _, _, aliases in FIELD_SPECS}
CONTEXT_WORDS = ('基本情况', '基本信息', '结论', '封面', '定级情况', '单位简介', '重大风险隐患', '扩展应用')
SUBJECT_LABELS = {'被测单位': 'tested', '测评单位': 'assessor', '编制单位': 'assessor'}
PHONE_IDS = {'tested_phone', 'assessor_phone'}


def _level_conflict(values):
    profiles, grades = set(), set()
    for value in values:
        profile = re.search(r'S\s*([1-5])\s*A\s*([1-5])(?:\s*G\s*([1-5]))?', value, re.I)
        if profile:
            s, a = int(profile[1]), int(profile[2])
            g = int(profile[3]) if profile[3] else max(s, a)
            profiles.add((s, a, g)); grades.add(g)
            continue
        grade = re.search(r'第\s*([一二三四五1-5])\s*级|([1-5])\s*级', value)
        if not grade:
            return len(set(values)) > 1
        token = grade[1] or grade[2]
        grades.add('一二三四五'.index(token) + 1 if token in '一二三四五' else int(token))
    return len(profiles) > 1 or len(grades) > 1


def _source(doc, table, cell):
    return {'document_id': doc.get('id'), 'document_sha256': doc.get('sha256') or
            doc.get('parsed', {}).get('document_sha256'), 'document_version': doc.get('version'),
            'table_id': table['table_id'], 'block_id': table.get('block_id'),
            'row': cell['row'], 'col': cell['col'], 'source_cell': cell.get('source_cell'),
            'chapter_path': table.get('chapter_path', []), 'caption': table.get('caption', '')}


def _table_kind(table, role):
    context = ' '.join(table.get('chapter_path', []) + [table.get('caption', '')])
    if not any(word in context for word in CONTEXT_WORDS):
        return None
    if '结论' in context or '重大风险隐患' in context:
        return 'conclusion'
    if '封面' in context:
        return 'cover'
    if '单位基本' in context or '单位简介' in context:
        return 'unit'
    if '对象基本' in context or '定级情况' in context:
        return 'object'
    return 'basic'


def _rank(field_id, kind, role):
    if field_id in ('conclusion', 'major_hazard_count'):
        return 0 if kind == 'conclusion' else 2
    if field_id.startswith('tested_') or field_id.startswith('assessor_') or field_id in ('credit_code', 'organization_code'):
        return 0 if role == 'survey' and kind == 'unit' or role != 'survey' and kind == 'basic' else 1
    if role == 'survey' and kind == 'object' or role != 'survey' and kind == 'basic':
        return 0
    return 1 if kind == 'conclusion' else 2


def _field_for(label, subject, role):
    key = _key(label)
    for field_id, _, _, _ in FIELD_SPECS:
        if key not in ALIASES[field_id]:
            continue
        if field_id.startswith('tested_') and subject == 'assessor':
            continue
        if field_id.startswith('assessor_') and subject != 'assessor' and key not in {_key(a) for a in ('测评单位', '测评单位名称', '测评单位全称', '编制单位')}:
            continue
        if field_id in ('conclusion', 'major_hazard_count') and role != 'report':
            continue
        return field_id
    return None


def _field_candidates(doc, role):
    output = {field_id: [] for field_id, _, _, _ in FIELD_SPECS}
    failed_kinds = set()
    for table in doc.get('parsed', {}).get('source_tables', []):
        kind = _table_kind(table, role)
        if kind is None:
            continue
        if table.get('parse_status') != 'parsed':
            failed_kinds.add(kind)
        if table.get('parse_status') not in ('parsed', 'nested_table'):
            continue
        rows = _row_cells(table)
        if kind == 'object' and len(rows) > 1:
            first = rows[min(rows)]
            header_fields = [(col, _field_for(cell.get('raw_value'), None, role)) for col, cell in first.items()]
            if sum(field_id is not None for _, field_id in header_fields) >= 2:
                values = rows[sorted(rows)[1]]
                for col, field_id in header_fields:
                    cell = values.get(col)
                    if field_id and cell:
                        output[field_id].append({'label': first[col]['raw_value'],
                                                 'value': str(cell.get('raw_value') or '').strip(),
                                                 'source': _source(doc, table, cell),
                                                 'rank': _rank(field_id, kind, role)})
                continue
        subject_by_col = {}
        if kind == 'unit' and role == 'survey':
            subject_by_col[1] = 'tested'
        for cells in rows.values():
            ordered = sorted(cells.items())
            seen_origins = set()
            for col, label_cell in ordered:
                origin = label_cell.get('source_cell')
                if origin in seen_origins:
                    continue
                seen_origins.add(origin)
                label = str(label_cell.get('raw_value') or '').strip()
                if not label:
                    continue
                if label in SUBJECT_LABELS:
                    subject_by_col[col] = SUBJECT_LABELS[label]
                next_cell = next((candidate for next_col, candidate in ordered if next_col > col and
                                  candidate.get('source_cell') != origin), None)
                if next_cell is None:
                    continue
                value = str(next_cell.get('raw_value') or '').strip()
                if label in SUBJECT_LABELS and not value:
                    continue
                subject = next((subject_by_col[c] for c in sorted(subject_by_col, reverse=True) if c <= col),
                               'tested' if kind == 'unit' else None)
                field_id = _field_for(label, subject, role)
                if field_id is None:
                    continue
                if field_id.startswith('assessor_') and role == 'survey' and kind != 'unit':
                    continue
                if field_id == 'tested_contact' and role == 'plan' and _key(label) == '联系人' and subject is None:
                    continue
                output[field_id].append({'label': label, 'value': value,
                                         'source': _source(doc, table, next_cell),
                                         'rank': _rank(field_id, kind, role)})
    return output, failed_kinds


def _field_source(doc, role, field_id):
    if not doc:
        return {'status': 'missing', 'value': None, 'candidates': []}
    candidates, failed_kinds = _field_candidates(doc, role)
    choices = candidates[field_id]
    public = [{k: v for k, v in item.items() if k != 'rank'} for item in choices]
    if not choices:
        failed = any(_rank(field_id, kind, role) == 0 for kind in failed_kinds)
        return {'status': 'parse_failed' if failed or doc.get('status') == 'failed' else 'missing',
                'value': None, 'candidates': []}
    valued = [item for item in choices if item['value']]
    if not valued:
        return {'status': 'empty', 'value': '', 'candidates': public}
    primary = min(valued, key=lambda item: item['rank'])
    if field_id in PHONE_IDS:
        phone_labels = ('办公电话', '移动电话', '联系电话', '电话', '手机')
        preferred = [item for item in valued if item['rank'] == primary['rank']]
        value = '\n'.join(f'{item["label"]}：{item["value"]}' for item in preferred
                          if any(word in item['label'] for word in phone_labels))
        value = value or primary['value']
    else:
        value = primary['value']
    if field_id in PHONE_IDS:
        phone_values = {}
        for item in valued:
            label = item['label']
            kind = 'mobile' if '移动' in label or '手机' in label else 'office' if '办公' in label else 'phone'
            phone_values.setdefault(kind, set()).add(item['value'])
        conflict = any(len(values) > 1 for values in phone_values.values())
    else:
        conflict = (_level_conflict([item['value'] for item in valued]) if field_id == 'protection_level'
                    else len({item['value'] for item in valued}) > 1)
    result = {'status': 'conflict' if conflict else 'value',
              'value': value, 'candidates': public}
    if field_id == 'protection_level':
        match = re.search(r'S\s*([1-5])\s*A\s*([1-5])(?:\s*G\s*([1-5]))?', value, re.I)
        if match and not match[3]:
            result['derived'] = {'g': max(int(match[1]), int(match[2])), 'basis': 'max(S,A)'}
    return result


def _count_source(doc, role, category, scope):
    empty = {'status': 'missing', 'total': None, 'importance': {'status': 'unknown', 'buckets': None},
             'duplicates': {'groups': 0, 'records': 0}, 'anomalies': [], 'records': []}
    if not doc or role == 'survey' and scope == 'sample':
        return empty
    position_id = f'{category["id"]}:{role}:{scope}'
    if not any(p['id'] == position_id for p in MAPPING['positions']):
        return empty | {'status': 'not_applicable'}
    position = locate_tables(doc.get('parsed', {}), role, scope).get(position_id)
    if not position or position['status'] == 'missing':
        return empty
    if position['status'] != 'matched':
        return empty | {'status': 'unknown', 'diagnostics': position['diagnostics'] or [position['status']]}
    table = next(t for t in doc['parsed']['source_tables'] if t['table_id'] == position['table_ids'][0])
    header_row = _header_row(table, category)
    columns = _field_header_map(table, category, header_row)
    name_field = next(f for f in category['fields'] if f['comparison'] == 'entity_name')
    name_col = columns[name_field['id']][0]
    importance_field = next((f for f in category['fields'] if f['label'] == '重要程度'), None)
    importance_cols = columns[importance_field['id']] if importance_field else []
    importance_col = importance_cols[0] if len(importance_cols) == 1 else None
    buckets = {'关键': 0, '重要': 0, '一般': 0, '未填写或无法识别': 0}
    records, anomalies, names, seen_origins = [], [], [], set()
    headers = {_key(cell['raw_value']) for cell in _row_cells(table)[header_row].values()}
    for row_number, row in sorted(_row_cells(table).items()):
        if row_number <= header_row:
            continue
        values = {_key(cell.get('raw_value')) for cell in row.values() if _key(cell.get('raw_value'))}
        if not values or values == headers:
            continue
        name_cell = row.get(name_col)
        name = str(name_cell.get('raw_value') or '').strip() if name_cell else ''
        if _key(name) in {'不涉及', '本次测评不涉及', '无', '不适用'} or re.match(r'^(合计|总计)', name):
            continue
        if not name:
            anomalies.append({'reason': 'nonempty_row_without_name', 'source':
                              _source(doc, table, next(iter(row.values())))})
            continue
        origin = name_cell.get('source_cell') if name_cell else None
        if origin and origin in seen_origins:
            continue
        if origin:
            seen_origins.add(origin)
        importance = str(row.get(importance_col, {}).get('raw_value') or '').strip() if importance_col else ''
        bucket = importance if importance in ('关键', '重要', '一般') else '未填写或无法识别'
        buckets[bucket] += 1
        records.append({'name': name, 'importance': importance, 'source': _source(doc, table, name_cell)})
        names.append(_key(name))
    repeated = [n for n in Counter(names).values() if n > 1]
    partial = bool(position['diagnostics']) or doc.get('status') == 'partial' and bool(anomalies)
    return {'status': 'partial' if partial else 'value', 'total': len(records),
            'importance': {'status': 'value' if importance_col else 'field_undefined',
                           'buckets': buckets if importance_col else None},
            'duplicates': {'groups': len(repeated), 'records': sum(repeated)},
            'anomalies': anomalies, 'records': records, 'diagnostics': position['diagnostics']}


def build_key_info(documents):
    """Build one comparable snapshot from the latest independent role documents."""
    fields = [{'id': field_id, 'label': label, 'group': group,
               'sources': {role: _field_source(documents.get(role), role, field_id) for role in ROLES}}
              for field_id, label, group, _ in FIELD_SPECS]
    counts = [{'category_id': category['id'], 'label': category['label'], 'scope': scope,
               'sources': {role: _count_source(documents.get(role), role, category, scope) for role in ROLES}}
              for scope in SCOPES for category in MAPPING['categories']]
    return {'fields': fields, 'counts': counts,
            'documents': {role: {'id': doc.get('id'), 'version': doc.get('version'),
                                 'sha256': doc.get('sha256'), 'status': doc.get('status')}
                          for role, doc in documents.items()}}
