"""Strict, evidence-preserving comparison of the three document extracts."""

import hashlib
import unicodedata
from collections import defaultdict

from .consistency_mapping import MAPPING


ROLES = {'full': ('survey', 'plan', 'report'), 'sample': ('plan', 'report')}
UNAVAILABLE = {'field_undefined', 'field_unmapped', 'mapping_unresolved',
               'not_applicable_field', 'ambiguous_header', 'missing_cell',
               'parse_failed', 'ambiguous', 'missing'}
UNCERTAIN = UNAVAILABLE | {'missing_object', 'duplicate_key'}
REVIEW_FIELDS = {'c10_f02', 'c10_f03'}


def entity_key(name):
    """Remove only Unicode whitespace and bracket marks, retaining their contents."""
    return ''.join(char for char in name
                   if not char.isspace() and unicodedata.category(char) not in {'Ps', 'Pe'})


def comparison_value(value):
    """Ignore edge whitespace and Word layout newlines, but preserve other characters."""
    return str('' if value is None else value).replace('\r', '').replace('\n', '').strip()


def _record_id(cell):
    source = cell.get('source') or {}
    return (source.get('table_id'), source.get('row'), cell['entity_name'])


def _status_for_absent(role, category_id, locations):
    location = locations.get(f'{category_id}:{role}:full') or locations.get(
        f'{category_id}:{role}:sample')
    if location and location.get('status') != 'matched':
        return location['status']
    return 'missing_object'


def _issue(scope, row, field_id, code, sources):
    evidence = []
    for role, cell in sources.items():
        originals = (record['cells'].get(field_id) or
                     {'status': 'missing_cell', 'raw_value': None, 'source': record['source']}
                     for record in row['source_records'][role]) if cell['status'] == 'duplicate_key' else (cell,)
        evidence.extend({'role': role, 'raw_value': original.get('raw_value'),
                         'status': original['status'], 'source': original.get('source')}
                        for original in originals)
    return {'scope': scope, 'row_id': row['id'], 'category_id': row['category_id'],
            'entity_key': row['entity_key'], 'field_id': field_id, 'code': code,
            'evidence': evidence}


def compare_documents(extracted: dict[str, list[dict]], locations: dict, scope: str) -> dict:
    """Compare aligned source rows; unresolved evidence never becomes agreement."""
    if scope not in ROLES:
        raise ValueError(f'unknown scope: {scope}')
    roles = ROLES[scope]
    positions = locations
    if any(role in locations for role in roles):
        positions = {key: value for role in roles for key, value in locations.get(role, {}).items()}
    diagnostics = [{'position_id': key, **value} for key, value in positions.items()
                   if value.get('status') != 'matched']
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    record_index = defaultdict(dict)
    for role in roles:
        for cell in extracted.get(role, []):
            if cell.get('scope') != scope:
                continue
            category_id, name = cell.get('category_id'), cell.get('entity_name')
            if not category_id or not name:
                diagnostics.append({'role': role, 'category_id': category_id,
                                    'status': cell.get('status'), 'source': cell.get('source'),
                                    'diagnostic': cell.get('diagnostic')})
                continue
            key = (category_id, entity_key(name))
            record_id = _record_id(cell)
            records = grouped[key][role]
            if record_id not in record_index[key, role]:
                record = {'entity_name': name, 'source': cell.get('source'), 'cells': {}}
                record_index[key, role][record_id] = record
                records[record_id].append(record)
            record_index[key, role][record_id]['cells'][cell['field_id']] = cell
    rows, issues = [], []
    categories = {category['id']: category for category in MAPPING['categories']}
    for category_id, key in sorted(grouped, key=lambda pair: (
            list(categories).index(pair[0]), pair[1])):
        by_role = grouped[category_id, key]
        records = {role: [item for batch in by_role.get(role, {}).values() for item in batch]
                   for role in roles}
        row_id = hashlib.sha256(f'{scope}:{category_id}:{key}'.encode()).hexdigest()[:16]
        row = {'id': row_id, 'scope': scope, 'category_id': category_id,
               'category': categories[category_id]['label'], 'entity_key': key,
               'original_names': {role: [record['entity_name'] for record in records.get(role, [])]
                                  for role in ('survey', 'plan', 'report')},
               'source_records': {role: records.get(role, []) for role in ('survey', 'plan', 'report')},
               'fields': {}}
        duplicate = any(len(records.get(role, [])) > 1 for role in roles)
        for field in categories[category_id]['fields']:
            field_id = field['id']
            sources = {}
            for role in roles:
                role_records = records.get(role, [])
                if len(role_records) == 1:
                    sources[role] = role_records[0]['cells'].get(field_id, {
                        'status': 'missing_cell', 'raw_value': None, 'source': role_records[0]['source']})
                elif len(role_records) > 1:
                    sources[role] = {'status': 'duplicate_key', 'raw_value': None,
                                     'source': [record['source'] for record in role_records],
                                     'records': [record['cells'].get(field_id) for record in role_records]}
                else:
                    sources[role] = {'status': _status_for_absent(role, category_id, positions),
                                     'raw_value': None, 'source': None}
            available = {role: comparison_value(cell.get('raw_value'))
                         for role, cell in sources.items() if cell['status'] in {'value', 'empty'}}
            report_cell = sources.get('report', {})
            if report_cell.get('status') == 'missing_object':
                different_sources = [role for role in roles if role in available or role == 'report']
            elif 'report' in available:
                different_sources = [role for role in roles if role != 'report' and
                                     (sources[role]['status'] == 'missing_object' or
                                      (role in available and available[role] != available['report']))]
            elif len(set(available.values())) > 1:
                different_sources = [role for role in roles if role in available]
            else:
                different_sources = [role for role in roles if sources[role]['status'] == 'missing_object']
            has_difference = bool(different_sources)
            incomplete = duplicate or any(cell['status'] in UNCERTAIN for cell in sources.values())
            codes = []
            if duplicate:
                codes.append('duplicate_key')
            for role, cell in sources.items():
                if cell['status'] in UNCERTAIN and cell['status'] != 'duplicate_key':
                    codes.append(f'{role}:{cell["status"]}')
            if has_difference:
                codes.append('different_value')
            if available and all(value == '' for value in available.values()) and len(available) == len(roles):
                codes.append('empty_value')
            if duplicate:
                status = 'duplicate_key'
            elif field_id in REVIEW_FIELDS and has_difference:
                status = 'needs_review'
            elif has_difference:
                status = 'different'
            elif incomplete:
                status = 'incomplete'
            elif 'empty_value' in codes:
                status = 'empty'
            else:
                status = 'consistent'
            row['fields'][field_id] = {'field_id': field_id, 'label': field['label'],
                                       'comparison': field['comparison'], 'sources': sources,
                                       'different_sources': different_sources,
                                       'has_difference': has_difference, 'incomplete': incomplete,
                                       'issue_codes': codes, 'status': status}
            issues.extend(_issue(scope, row, field_id, code, sources) for code in codes)
        row['has_difference'] = any(field['has_difference'] for field in row['fields'].values())
        row['incomplete'] = any(field['incomplete'] for field in row['fields'].values())
        row['status'] = ('duplicate_key' if duplicate else
                         'missing_object' if any(not records.get(role) for role in roles) else
                         'needs_review' if any(f['status'] == 'needs_review' for f in row['fields'].values()) else
                         'different' if row['has_difference'] else
                         'incomplete' if row['incomplete'] else
                         'consistent')
        rows.append(row)
    completeness = not diagnostics and all(not row['incomplete'] for row in rows)
    return {'mapping_version': MAPPING['mapping_version'], 'scope': scope,
            'rows': rows, 'issues': issues, 'diagnostics': diagnostics,
            'completeness': completeness}
