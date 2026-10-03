"""Deterministic checks produce evidence-backed candidates, never silent truth overrides."""
import re
import string
from collections import defaultdict
from difflib import SequenceMatcher

from .catalog import norm
from .consistency import compare_documents
from .consistency_mapping import extract_cells, locate_tables


def compare_consistency(documents, scope='full'):
    """New asset boundary; legacy compare_assets remains for existing run routes."""
    roles = ('survey', 'plan', 'report') if scope == 'full' else ('plan', 'report')
    parsed = {role: (documents.get(role) or {}).get('parsed') or {} for role in roles}
    locations = {key: location for role in roles
                 for key, location in locate_tables(parsed[role], role, scope).items()}
    extracted = {role: extract_cells(parsed[role], role, scope) for role in roles}
    return compare_documents(extracted, locations, scope)


def field_norm(key,value):
    text=norm(value)
    if 'ip' in norm(key):
        return tuple(sorted(set(re.findall(r'(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?|[a-fA-F\d:]{3,}:[a-fA-F\d:]*',str(value))))) or text
    return text


def canonical_field(key):
    value=norm(key)
    for words,name in [(['ip地址','ip'],'ip'),(['品牌','型号'],'brand_model'),(['操作系统','系统及版本','系统/版本'],'system_version'),(['物理位置'],'location'),(['重要程度'],'importance'),(['用途','主要功能'],'purpose'),(['虚拟设备'],'virtual'),(['数量'],'quantity')]:
        if any(x in value for x in words):return name
    return value


def issue(chapter,category,title,description,suggestion,obj='',evidence=None,**more):
    return {'chapter':chapter,'category':category,'title':title,'description':description,'suggestion':suggestion,'object_name':obj,'evidence':evidence or [],'machine':more}


def compare_assets(documents, scope='full', aliases=None):
    roles=['survey','plan','report'] if scope=='full' else ['plan','report']
    groups=defaultdict(lambda:defaultdict(list)); issues=[]; rows=[]
    aliases=aliases or {}
    for role in roles:
        doc=documents.get(role)
        if not doc or doc.get('status') not in ['parsed','partial']: raise ValueError('需要所选范围的所有文档解析成功')
        items=[a for a in doc['parsed']['assets'] if a['scope']==('full' if scope=='full' else ('planned_sample' if role=='plan' else 'actual_sample'))]
        if not items: raise ValueError(f'{role} 未识别到{scope}清单，先确认表格范围；不能把未解析当资产缺失')
        for a in items:
            alias_key=f'{role}:{doc.get("id", "")}:{a["id"]}' if doc.get('id') else f'{role}:{a["id"]}'
            name=aliases.get(alias_key,a['name'])
            a={**a,'alias_key':alias_key}
            groups[(a['type'],norm(name))][role].append(a)
    for (kind,key),by_role in groups.items():
        name=next(iter(by_role.values()))[0]['name']
        ev=[{'role':role,'quote':a['name']+' '+str(a['attributes']),'source':a['source']} for role,vals in by_role.items() for a in vals]
        status='consistent'; differences=[]
        if any(len(v)>1 for v in by_role.values()):
            status='ambiguous';issues.append(issue('CROSS_DOCUMENT','asset_match','同名对象需要确认',f'{name} 在同一来源中出现多次，未自动合并。','核对对象身份、表格范围和重复记录。',name,ev))
        elif len(by_role)<len(roles):
            status='missing'; missing=[r for r in roles if r not in by_role]
            issues.append(issue('CROSS_DOCUMENT','asset_missing','对象未在全部对照来源中找到',f'{name} 未在 {", ".join(missing)} 的指定清单中匹配到。','先确认别名或合法变更；不能默认报告为正确值。',name,ev))
        else:
            attrs={r:{canonical_field(k):v for k,v in vals[0]['attributes'].items()} for r,vals in by_role.items()}
            field_keys=set.intersection(*(set(x) for x in attrs.values()))
            for f in sorted(field_keys):
                values={r:attrs[r][f] for r in roles}
                if len({str(field_norm(f,v)) for v in values.values()})>1:
                    differences.append({'field':f,'values':values})
            if differences:
                status='different';issues.append(issue('CROSS_DOCUMENT','asset_difference',f'{name} 存在属性差异','；'.join(d['field'] for d in differences),'并列核对原始值；自由文本差异需审核员确认语义。',name,ev,differences=differences))
        rows.append({'name':name,'type':kind,'status':status,'sources':dict(by_role),'differences':differences})
    return {'rows':rows,'issues':issues,'scope':scope}


def match_requirement(record, requirements, override=None):
    if override:
        found=[r for r in requirements if r['key']==override]
        return {'status':'matched','requirement':found[0],'method':'manual'} if len(found)==1 else {'status':'unmatched','candidates':[]}
    pool=[r for r in requirements if r['domain']==record['domain'] and r['family']==record['extension']]
    def clean(t):
        return re.sub(r'[^\w\u4e00-\u9fff]','',norm(t).replace('测评指标',''))
    target=clean(record['requirement'])
    exact=[r for r in pool if clean(r['text'])==target]
    if len(exact)==1: return {'status':'matched','requirement':exact[0],'method':'exact'}
    ranked=sorted([{'key':r['key'],'text':r['text'],'source':r['source'],'score':round(SequenceMatcher(None,target,clean(r['text'])).ratio(),3)} for r in pool],key=lambda r:r['score'],reverse=True)[:3]
    # ponytail: fuzzy matches are suggestions; reviewers confirm before model calls.
    return {'status':'ambiguous' if ranked else 'unmatched','candidates':ranked}


def _risk_values(table, row):
    """Return a row's values without changing the parser's raw representation."""
    if isinstance(row, dict):
        raw = row.get('values') or row.get('raw_values')
        if isinstance(raw, dict):
            return dict(raw), raw
        if raw is not None:
            row = raw
    headers = table.get('headers') or []
    if isinstance(row, dict):
        return dict(row), row
    values = {str(header): row[index] for index, header in enumerate(headers)
              if header and index < len(row)}
    return values, row


def _risk_text(values, names):
    """Find a value by header fragments, accepting both Chinese and English fixtures."""
    for key, value in values.items():
        key_text = norm(key)
        if any(norm(name) in key_text for name in names):
            return '' if value is None else str(value).strip()
    return ''


def _risk_description(values):
    names = ('问题描述', '安全问题', '问题', '场景', 'description', 'scenario')
    for key, value in values.items():
        key_text = norm(key)
        if not value or '编号' in key_text or '分析' in key_text:
            continue
        if any(norm(name) in key_text for name in names):
            return str(value).strip()
    return ''


def _risk_applicability(rule, config):
    """Resolve only explicit applicability; absent/ambiguous data remains pending."""
    key = str(rule.get('key', ''))
    overrides = (config or {}).get('applicability', {})
    override = overrides.get(key) if isinstance(overrides, dict) else None
    values = [override] if override is not None else [
        rule.get('applicability_status'), rule.get('applicability'),
        rule.get('applicable'), rule.get('scope')]
    for value in values:
        if isinstance(value, bool):
            return 'applicable' if value else 'not_applicable'
        text = norm(value)
        if not text:
            continue
        if text in {'not_applicable', 'excluded', '不适用', '不涉及', '否'} or '明确不适用' in text:
            return 'not_applicable'
        if text in {'applicable', '适用', '是'}:
            return 'applicable'
    return 'pending'


def _risk_grade_conflict(entry):
    analysis = entry.get('analysis', '')
    grade = entry.get('grade', '')
    if not analysis or not grade:
        return None
    stated = re.search(r'(?:故判为|判定为|判为|评定为|determined\s+as)\s*([高中低]|high|medium|low)\s*(?:风险|risk)?', analysis, re.I)
    if not stated:
        return None
    grade_text = norm(grade)
    stated_text = norm(stated.group(1))
    aliases = {'高': 'high', '中': 'medium', '低': 'low', 'high': 'high', 'medium': 'medium', 'low': 'low'}
    expected = aliases.get(stated_text, stated_text)
    actual = next((name for token, name in aliases.items() if token in grade_text), grade_text)
    if expected == actual:
        return None
    return {'type': 'grade_conflict', 'expected': stated.group(1), 'actual': grade,
            'row_id': entry['row_id'], 'source': entry['source']}


LEGACY_RISK_COLUMNS = (
    '序号', '问题编号', '报告安全问题描述', '报告4.3整体测评描述', '报告第5章问题风险分析',
    '报告涉及对象', '高风险条款号', '适用范围', '报告判定', '是否重大风险',
    '指引-场景/问题描述', '指引-可能的缓解措施', '指引-风险评价-参考',
)


_LEGACY_RISK_PUNCTUATION = str.maketrans('', '', string.punctuation + '，。！？；："《》【】（）｛｝、·￥……—')


def _legacy_risk_clean(value):
    text = re.sub(r'\s+', '', str(value if value is not None else ''))
    return re.sub(r'[a-zA-Z]', '', text).translate(_LEGACY_RISK_PUNCTUATION).strip()


def _legacy_risk_score(left, right):
    return round(100 * SequenceMatcher(None, _legacy_risk_clean(left), _legacy_risk_clean(right)).ratio())


def legacy_risk_rows(source_rows, guide_rows):
    """Recreate the desktop tool's 13-column matched view from parsed rows."""
    overall = [row for row in source_rows if row.get('kind') == 'overall']
    analysis = [row for row in source_rows if row.get('kind') == 'risk']
    result = []
    for problem in (row for row in source_rows if row.get('kind') == 'problem'):
        requirement = _legacy_risk_clean(_risk_text(problem.get('values', {}), ('测评项', 'requirement')))
        if not requirement:
            continue
        ranked = [(_legacy_risk_score(requirement, rule.get('requirement')), rule)
                  for rule in guide_rows if _legacy_risk_clean(rule.get('requirement'))]
        if not ranked:
            continue
        score, guide = max(ranked, key=lambda item: item[0])
        if score < 98:
            continue
        description = problem.get('description', '')
        def related(rows):
            return next((row for row in rows if row.get('description')
                         and _legacy_risk_score(description, row['description']) >= 98), {})
        overall_row, risk_row = related(overall), related(analysis)
        values = dict(zip(LEGACY_RISK_COLUMNS, (
            len(result) + 1,
            _risk_text(problem.get('values', {}), ('问题编号', '序号')),
            description,
            _risk_text(overall_row.get('values', {}), ('整体测评描述', 'overall description')),
            _risk_text(risk_row.get('values', {}), ('危害分析结果', '风险分析', 'risk analysis')),
            problem.get('object', ''), guide.get('clause', ''), guide.get('scope', ''),
            risk_row.get('grade', ''), guide.get('major', ''), guide.get('scenario', ''),
            guide.get('mitigation', ''), guide.get('evaluation', ''),
        )))
        result.append({'source_row_id': problem.get('row_id'), 'guide_key': guide.get('key'),
                       'score': score, 'values': values,
                       'source_locations': [row.get('table_location') for row in (problem, overall_row, risk_row) if row]})
    return result


def risk_review(parsed, guide, config=None):
    """Build a complete, reviewable four-way risk comparison.

    Similarity only creates links for reviewer consideration.  It never sets a
    high-risk conclusion, and every non-empty source row remains in the result.
    ``config`` is optional for compatibility with existing run routes.
    """
    config = config or {}
    guide = list(guide or [])
    source_rows, linked, candidates, issues, links, unmatched, conflicts = [], [], [], [], [], [], []
    tables = parsed.get('risk_tables', []) if parsed else []
    threshold = float(config.get('similarity_threshold', 0.3))
    limit = int(config.get('max_candidates', 3))
    for table_index, table in enumerate(tables):
        headers = table.get('headers') or []
        rows = table.get('rows') or []
        for row_index, row in enumerate(rows):
            values, raw = _risk_values(table, row)
            raw_values = row.get('raw_values', raw) if isinstance(row, dict) else raw
            text = ' '.join(str(v) for v in (raw_values.values() if isinstance(raw_values, dict) else (raw_values or [])))
            # Keep blank rows as parse diagnostics when a parser supplied a row ID;
            # ordinary blank padding rows are not useful source records.
            row_id = (row.get('row_id') if isinstance(row, dict) else None) or \
                f"risk:{table.get('chapter', '')}:{table.get('source', table_index)}:{row_index + 1}"
            description = _risk_description(values)
            obj = _risk_text(values, ('关联资产', '对象', '资产', 'object', 'asset'))
            analysis = _risk_text(values, ('风险分析', '危害分析', 'risk_analysis', 'analysis'))
            grade = _risk_text(values, ('风险等级', '风险程度', 'risk_grade', 'grade'))
            source = f"{table.get('source', '')} · 数据行{row_index + 1}"
            entry = {
                'row_id': row_id, 'kind': table.get('kind', ''),
                'chapter': table.get('chapter', ''),
                'table_location': table.get('table_location', table.get('source', '')),
                'row_number': (row.get('row_number') if isinstance(row, dict) else None) or row_index + 1,
                'raw_values': raw_values, 'values': values,
                'parse_status': (row.get('parse_status') if isinstance(row, dict) else None) or ('parsed' if description else 'unparsed'),
                'description': description, 'object': obj, 'analysis': analysis, 'grade': grade,
                'source': source,
            }
            source_rows.append(entry)
            if not text.strip() and not isinstance(row, dict):
                continue
            linked.append({'row_id': row_id, 'kind': entry['kind'], 'description': description,
                           'object': obj, 'source': source, 'values': values})
            conflict = _risk_grade_conflict(entry) if entry['kind'] in {'risk', 'overall'} else None
            if conflict:
                conflicts.append(conflict)
                issues.append(issue('CH05', 'risk_consistency', '风险分析与风险等级不一致',
                                    f"分析文字为“{conflict['expected']}”，等级列为“{conflict['actual']}”。",
                                    '核实正确结论后统一文字、等级和关联汇总。', obj,
                                    [{'source': source, 'quote': analysis}, {'source': source, 'quote': grade}],
                                    conflict_type='grade_conflict', row_id=row_id))
            if not description:
                unmatched.append({'source_row_id': row_id, 'row_id': row_id, 'reason': 'missing_description', 'source': source})
                continue
            ranking = []
            for rule in guide:
                applicability = _risk_applicability(rule, config)
                if applicability == 'not_applicable':
                    continue
                scenario = rule.get('scenario') or rule.get('description') or rule.get('text') or ''
                score = SequenceMatcher(None, norm(description), norm(scenario)).ratio()
                if score >= threshold:
                    ranking.append({**rule, 'score': round(score, 3), 'applicability': applicability})
            ranking.sort(key=lambda candidate: (-candidate['score'], str(candidate.get('key', ''))))
            ranking = ranking[:limit]
            candidate = {'row_id': row_id, 'source_row_id': row_id, 'description': description,
                         'object': obj, 'source': source, 'matches': ranking,
                         'status': 'candidate' if ranking else 'unmatched',
                         'major_hazard_assessment': 'pending', 'final_conclusion': None}
            candidates.append(candidate)
            if not ranking:
                unmatched.append({'source_row_id': row_id, 'row_id': row_id, 'reason': 'no_guide_candidate', 'source': source})
            for match in ranking:
                guide_key = match.get('key') or match.get('id') or f'guide:{guide.index(match)}'
                link = {'link_id': f'{row_id}:{guide_key}', 'id': f'{row_id}:{guide_key}',
                        'source_row_id': row_id, 'guide_key': guide_key,
                        'candidate_key': guide_key, 'score': match['score'],
                        'applicability': match['applicability'], 'status': 'candidate',
                        'machine_conclusion': None, 'match_basis': 'description_similarity',
                        'guide_source': match.get('source', '')}
                links.append(link)
            evidence = [{'role': 'report', 'source': source, 'quote': description}]
            evidence += [{'role': 'knowledge', 'source': x.get('source', ''), 'quote': x.get('scenario', '')} for x in ranking]
            if entry['kind'] == 'problem':
                issues.append(issue('MAJOR_HAZARD', 'high_risk_screening', '高风险判定待人工核对', description,
                                    '核对指引条件、缓解措施、整体测评和风险分析后记录是否成立。', obj, evidence,
                                    guide_candidates=[{'key': x.get('key'), 'source': x.get('source'), 'score': x['score']} for x in ranking],
                                    auto_conclusion='none', row_id=row_id))
            elif entry['kind'] == 'hazard':
                issues.append(issue('MAJOR_HAZARD', 'major_hazard_table', '重大风险隐患表需与问题核对', description,
                                    '核对触发项是否有对应的报告证据和风险分析。', obj,
                                    [{'role': 'report', 'source': source, 'quote': description}],
                                    auto_conclusion='none', row_id=row_id))
    if not linked:
        # Preserve parser output for manual review. The precheck blocks a run
        # with no risk tables; this branch covers malformed or blank tables and
        # must not turn them into a false "no high risk" conclusion.
        return {'source_rows': source_rows, 'guide_rows': [{**rule, 'applicability': _risk_applicability(rule, config)} for rule in guide],
                'links': links, 'unmatched': unmatched, 'conflicts': conflicts,
                'applicability': {row.get('key', row.get('id', str(i))): row['applicability']
                                  for i, row in enumerate([{**rule, 'applicability': _risk_applicability(rule, config)} for rule in guide])},
                'legacy_rows': [], 'candidates': candidates, 'issues': issues + [issue('MAJOR_HAZARD', 'high_risk_screening',
                                  '高风险来源待核实', '报告来源行未能解析为可关联的风险对象。',
                                  '人工核对原始报告表格和章节范围。')], 'linked_rows': linked,
                'guide_available': bool(guide),
                'note': '未能解析可关联的风险来源行，不能据此认定无高风险。'}
    for candidate in candidates:
        candidate['related'] = [x for x in linked if x['row_id'] != candidate['row_id'] and x['kind'] != 'problem'
                                and norm(x['description']) == norm(candidate['description'])
                                and (not candidate['object'] or not x['object'] or norm(x['object']) == norm(candidate['object']))]
    guide_rows = [{**rule, 'applicability': _risk_applicability(rule, config)} for rule in guide]
    return {'source_rows': source_rows, 'guide_rows': guide_rows,
            'legacy_rows': legacy_risk_rows(source_rows, guide_rows), 'links': links,
            'unmatched': unmatched, 'conflicts': conflicts, 'applicability':
            {row.get('key', row.get('id', str(i))): row['applicability'] for i, row in enumerate(guide_rows)},
            'candidates': candidates, 'issues': issues, 'linked_rows': linked,
            'guide_available': bool(guide),
            'note': '指引匹配为候选，未自动判定高风险或重大隐患成立。'}

