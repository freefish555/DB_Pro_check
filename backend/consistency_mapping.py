"""Versioned source-table locator and raw-cell extraction for three DOCX roles."""

import json
import re
from pathlib import Path


MAPPING = json.loads(Path(__file__).with_name('consistency_mapping.json').read_text(encoding='utf-8'))
ROLE = {'scheme': 'plan', 'survey': 'survey', 'plan': 'plan', 'report': 'report'}
SCOPE = {'all': 'full', 'selected': 'sample', 'full': 'full', 'sample': 'sample'}
NO_OBJECT = {'不涉及', '本次测评不涉及', '无', '不适用'}


def _key(value):
    """Ignore layout whitespace and the survey's checkbox instruction only."""
    value = re.sub(r'\s+', '', str(value or ''))
    value = re.sub(r'\(?请勾选[^)]*\)?|（请勾选[^）]*）', '', value)
    return re.sub(r'[（(]√/×[）)]?', '', value)


def _chapter(path):
    for title in path:
        match = re.match(r'\s*(?:第\s*([1-8])\s*章|([1-8])\s*[.、\s])', title)
        if match:
            return int(match[1] or match[2])
        if re.match(r'\s*附录\s*A', title, re.I):
            return 'A'
    return None


def _expected_chapter(role, scope):
    return {('plan', 'full'): (2, 'A'), ('plan', 'sample'): 3,
            ('report', 'full'): 'A', ('report', 'sample'): 2}.get((role, scope))


def _section_hint(path, role, scope):
    text = ' / '.join(path)
    if role == 'plan':
        return ('测评对象选择结果' in text or '测评对象选择' in text) if scope == 'sample' else '系统构成' in text
    if role == 'report':
        return ('测评对象资产' in text or '被测对象资产' in text) if scope == 'full' else '测评对象选择' in text
    return True


def _category_hint(table, category):
    return any(_key(alias) in _key(title) for alias in category['title_aliases']
               for title in table.get('parent_titles', []))


def _row_cells(table):
    rows = {}
    for cell in table.get('cells', []):
        rows.setdefault(cell['row'], {})[cell['col']] = cell
    return rows


def _aliases(field):
    return {_key(alias) for alias in field.get('header_aliases', [field['label']]) if _key(alias)}


def _header_row(table, category):
    rows = _row_cells(table)
    name_fields = [field for field in category['fields'] if field['comparison'] == 'entity_name']
    if len(name_fields) != 1:
        return None
    name_aliases = _aliases(name_fields[0])
    for number in sorted(rows)[:6]:
        headers = {_key(cell['raw_value']) for cell in rows[number].values()}
        if headers & name_aliases and sum(bool(headers & _aliases(field)) for field in category['fields']) >= 2:
            return number
    return None


def _candidate(table, category, role, scope):
    path = table.get('chapter_path', [])
    if not _category_hint(table, category):
        return None
    text = ' / '.join(path)
    if scope == 'full' and ('测评对象选择结果' in text or '测评对象选择' in text):
        return None
    if scope == 'sample' and ('系统构成' in text or '被测对象资产' in text or '测评对象资产' in text):
        return None
    chapter = _chapter(path)
    expected = _expected_chapter(role, scope)
    if expected is not None and chapter is not None and chapter not in (expected if isinstance(expected, tuple) else (expected,)):
        return 'chapter_conflict'
    if chapter is None and not _section_hint(path, role, scope):
        return None
    if table.get('parse_status') != 'parsed':
        return 'parse_failed'
    if _header_row(table, category) is None:
        return None
    return 'matched'


def locate_tables(parsed: dict, role: str, scope: str) -> dict:
    """Find each logical source position; never choose an ambiguous table."""
    role, scope = ROLE[role], SCOPE[scope]
    positions = [p for p in MAPPING['positions'] if p['role'] == role and p['scope'] == scope]
    result = {}
    for position in positions:
        category = next(c for c in MAPPING['categories'] if c['id'] == position['category_id'])
        matches, problems = [], []
        for table in parsed.get('source_tables', []):
            status = _candidate(table, category, role, scope)
            if status == 'matched':
                header_row = _header_row(table, category)
                signature = _field_header_map(table, category, header_row)
                matches.append((table['table_id'], sum(len(cols) == 1 for cols in signature.values())))
            elif status:
                problems.append({'table_id': table['table_id'], 'status': status})
        if matches:
            best = max(score for _, score in matches)
            matches = [table_id for table_id, score in matches if score == best]
        if len(matches) > 1:
            status, ids = 'ambiguous', matches
        elif matches:
            status, ids = 'matched', matches
        elif problems:
            status, ids = 'parse_failed', [p['table_id'] for p in problems]
        else:
            status, ids = 'missing', []
        result[position['id']] = {
            'status': status, 'table_ids': ids,
            'diagnostics': sorted({p['status'] for p in problems}),
            'position_id': position['id'], 'category_id': category['id'],
            'role': role, 'scope': scope,
        }
    return result


def _field_header_map(table, category, header_row):
    row = _row_cells(table)[header_row]
    headers = {col: _key(cell['raw_value']) for col, cell in row.items()}
    return {field['id']: [col for col, value in headers.items() if value in _aliases(field)]
            for field in category['fields']}


def _cell_source(table, row, col, cell=None):
    return {'table_id': table['table_id'], 'row': row, 'col': col,
            'source_cell': cell['source_cell'] if cell else None,
            'chapter_path': table.get('chapter_path', []), 'caption': table.get('caption', '')}


def _exception(category, role, scope, status, source=None, diagnostic=None):
    return {'category_id': category['id'], 'entity_name': None, 'field_id': None,
            'role': role, 'scope': scope, 'raw_value': None, 'status': status,
            'source': source, 'diagnostic': diagnostic}


def _unavailable_status(field, role, scope):
    source = next((source for source in field['sources']
                   if source['role'] == role and source['scope'] == scope), None)
    policy = source['availability_policy'] if source else 'VALUE_OR_EMPTY'
    return {'FIELD_UNDEFINED': 'field_undefined',
            'MAPPING_UNRESOLVED': 'mapping_unresolved',
            'NOT_APPLICABLE': 'not_applicable_field'}.get(policy, 'field_unmapped')


def extract_cells(parsed: dict, role: str, scope: str) -> list[dict]:
    """Emit source cells with explicit absence and parse states, never inferred values."""
    role, scope = ROLE[role], SCOPE[scope]
    locations = locate_tables(parsed, role, scope)
    tables = {table['table_id']: table for table in parsed.get('source_tables', [])}
    output = []
    for position in MAPPING['positions']:
        if position['role'] != role or position['scope'] != scope:
            continue
        category = next(c for c in MAPPING['categories'] if c['id'] == position['category_id'])
        location = locations[position['id']]
        if location['status'] != 'matched':
            output.append(_exception(category, role, scope, location['status'], diagnostic=location['diagnostics']))
            continue
        table = tables[location['table_ids'][0]]
        header_row = _header_row(table, category)
        field_columns = _field_header_map(table, category, header_row)
        name_field = next(f for f in category['fields'] if f['comparison'] == 'entity_name')
        name_columns = field_columns[name_field['id']]
        if len(name_columns) != 1:
            output.append(_exception(category, role, scope, 'parse_failed',
                                     diagnostic='missing_or_ambiguous_entity_header'))
            continue
        rows = _row_cells(table)
        for row_number in sorted(rows):
            if row_number <= header_row:
                continue
            row = rows[row_number]
            if not any(_key(c['raw_value']) for c in row.values()):
                continue
            name_cell = row.get(name_columns[0])
            name = name_cell['raw_value'].strip() if name_cell else ''
            source = _cell_source(table, row_number, name_columns[0], name_cell)
            nonempty_values = {_key(cell['raw_value']) for cell in row.values() if _key(cell['raw_value'])}
            explanation = _key(name) in NO_OBJECT or _key(name).startswith('本次测评不涉及')
            if explanation and nonempty_values == {_key(name)}:
                output.append(_exception(category, role, scope, 'not_applicable', source))
                continue
            if not name and nonempty_values:
                output.append(_exception(category, role, scope, 'parse_failed', source,
                                         'nonempty_row_without_name'))
                continue
            if not name:
                continue
            for field in category['fields']:
                columns = field_columns[field['id']]
                if len(columns) != 1:
                    status = _unavailable_status(field, role, scope) if not columns else 'ambiguous_header'
                    value, col, cell = None, None, None
                else:
                    col = columns[0]
                    cell = row.get(col)
                    value = cell['raw_value'] if cell else None
                    status = 'missing_cell' if cell is None else ('empty' if not value.strip() else 'value')
                output.append({'category_id': category['id'], 'entity_name': name,
                               'field_id': field['id'], 'role': role, 'scope': scope,
                               'raw_value': value, 'status': status,
                               'source': _cell_source(table, row_number, col, cell),
                               'diagnostic': None})
    return output
