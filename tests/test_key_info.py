"""Synthetic source-table checks for the key-information view."""

import os
import tempfile

os.environ['REVIEW_DATA_DIR'] = tempfile.mkdtemp(prefix='key-info-')

from backend.key_info import build_key_info


def table(table_id, title, rows, chapter=None, status='parsed'):
    cells = []
    for row_number, values in enumerate(rows, 1):
        for col_number, value in enumerate(values, 1):
            cells.append({'row': row_number, 'col': col_number, 'raw_value': value,
                          'raw_label': '', 'source_cell': f'{table_id}r{row_number}c{col_number}',
                          'grid_span': 1, 'v_merge': None})
    return {'table_id': table_id, 'caption': title, 'chapter_path': chapter or [title],
            'parent_titles': chapter or [title], 'cells': cells, 'parse_status': status,
            'block_id': table_id + '-block'}


def doc(role, tables, status='parsed'):
    return {'id': role + '-id', 'version': 2, 'sha256': role + '-sha', 'status': status,
            'parsed': {'source_tables': tables}}


def source(payload, field_id, role):
    return next(row for row in payload['fields'] if row['id'] == field_id)['sources'][role]


def count(payload, category_id, scope, role):
    return next(row for row in payload['counts']
                if row['category_id'] == category_id and row['scope'] == scope)['sources'][role]


def test_unit_subject_and_phone_types_stay_separate_across_reordered_tables():
    report = doc('report', [
        table('t9', '附录 A 网络设备', [['设备名称', '重要程度'], ['交换机', '关键']]),
        table('t2', '报告基本信息表', [
            ['被测单位', '', '测评单位', ''],
            ['联系人', '王甲', '联系人', '李乙'],
            ['办公电话', '010-123', '移动电话', '13800000000'],
        ]),
    ])
    payload = build_key_info({'report': report})
    assert source(payload, 'tested_contact', 'report')['value'] == '王甲'
    assert source(payload, 'assessor_contact', 'report')['value'] == '李乙'
    assert source(payload, 'tested_phone', 'report')['value'] == '办公电话：010-123'
    assert source(payload, 'assessor_phone', 'report')['value'] == '移动电话：13800000000'
    assert source(payload, 'tested_contact', 'survey')['status'] == 'missing'


def test_primary_basic_source_keeps_conflicting_cover_candidate_and_empty_cell():
    survey = doc('survey', [
        table('t7', '封面', [['系统名称', '甲系统旧名']]),
        table('t1', '等级保护对象基本情况表', [['系统名称', '甲系统'], ['备案编号', '']]),
    ])
    payload = build_key_info({'survey': survey})
    system = source(payload, 'system_name', 'survey')
    assert system['status'] == 'conflict'
    assert system['value'] == '甲系统'
    assert {item['value'] for item in system['candidates']} == {'甲系统', '甲系统旧名'}
    assert all(item['source']['document_id'] == 'survey-id' for item in system['candidates'])
    assert source(payload, 'filing_number', 'survey')['status'] == 'empty'
    assert source(payload, 'filing_number', 'plan')['status'] == 'missing'


def test_phone_conflicts_are_checked_within_each_phone_type():
    report = doc('report', [table('t1', '报告基本信息表', [
        ['被测单位', ''], ['办公电话', '010-11111111'],
        ['移动电话', '13800000000'], ['手机', '13800000000'],
    ])])
    assert source(build_key_info({'report': report}), 'tested_phone', 'report')['status'] == 'value'
    report['parsed']['source_tables'].append(table('t2', '报告基本信息表', [
        ['被测单位', ''], ['办公电话', '010-22222222'],
    ]))
    result = source(build_key_info({'report': report}), 'tested_phone', 'report')
    assert result['status'] == 'conflict'
    assert '010-11111111' in result['value'] and '010-22222222' in result['value']


def test_profile_without_g_keeps_raw_value_and_derived_basis_separate():
    plan = doc('plan', [table('t1', '方案基本信息表', [['等级', 'S3A2']])])
    result = source(build_key_info({'plan': plan}), 'protection_level', 'plan')
    assert result['value'] == 'S3A2'
    assert result['derived'] == {'g': 3, 'basis': 'max(S,A)'}


def test_profile_and_matching_overall_grade_are_not_an_internal_conflict():
    plan = doc('plan', [
        table('t1', '方案基本信息表', [['安全保护等级', '第三级（S2A3G3）']]),
        table('t2', '等级保护对象基本情况表', [['安全保护等级', '第三级']]),
    ])
    result = source(build_key_info({'plan': plan}), 'protection_level', 'plan')
    assert result['status'] == 'value'
    assert len(result['candidates']) == 2


def test_real_template_aliases_and_horizontal_object_table_are_read():
    survey = doc('survey', [table('t3', '等级保护对象基本情况表', [
        ['', '定级对象名称', '安全保护等级（SxAx）', '备案证明编号'],
        ['1', '甲系统', 'S3A2', '000123'],
    ])])
    payload = build_key_info({'survey': survey})
    assert source(payload, 'system_name', 'survey')['value'] == '甲系统'
    assert source(payload, 'protection_level', 'survey')['value'] == 'S3A2'
    assert source(payload, 'filing_number', 'survey')['value'] == '000123'


def test_merged_subject_heading_is_not_mistaken_for_unit_name():
    basic = table('t2', '报告基本信息表', [
        ['被测单位', '被测单位', '被测单位', '被测单位'],
        ['单位名称', '甲单位', '', ''],
        ['测评单位', '测评单位', '测评单位', '测评单位'],
        ['单位名称', '乙单位', '', ''],
    ])
    for cell in basic['cells']:
        if cell['row'] in (1, 3):
            cell['source_cell'] = f't2r{cell["row"]}c1'
    payload = build_key_info({'report': doc('report', [basic])})
    assert source(payload, 'tested_name', 'report')['value'] == '甲单位'
    assert source(payload, 'assessor_name', 'report')['value'] == '乙单位'
    assert source(payload, 'tested_name', 'report')['status'] == 'value'


def test_missing_field_does_not_inherit_unrelated_cover_parse_failure():
    survey = doc('survey', [table('t1', '封面', [['系统名称', '甲系统']], status='unknown_section')])
    assert source(build_key_info({'survey': survey}), 'filing_number', 'survey')['status'] == 'missing'


def test_outer_cells_survive_a_nested_table_elsewhere_in_basic_information():
    plan = doc('plan', [table('t2', '方案基本信息表', [
        ['备案证明编号', '000123'], ['其他嵌套内容', ''],
    ], status='nested_table')], status='partial')
    payload = build_key_info({'plan': plan})
    assert source(payload, 'filing_number', 'plan')['value'] == '000123'
    assert source(payload, 'tested_name', 'plan')['status'] == 'parse_failed'


def test_count_uses_entity_rows_not_quantity_and_keeps_duplicates_and_anomalies():
    network = table('t6', '网络设备', [
        ['设备名称', '数量（台/套）', '重要程度'],
        ['交换机甲', '20台', '关键'],
        ['交换机甲', '1台', '重要'],
        ['', '3台', '一般'],
        ['合计', '24台', ''],
        ['不涉及', '', ''],
        ['设备名称', '数量（台/套）', '重要程度'],
        ['路由器乙', '2台', '未知'],
    ], ['第2章 系统构成', '网络设备'])
    result = count(build_key_info({'plan': doc('plan', [network])}), 'c02', 'full', 'plan')
    assert result['status'] == 'value'
    assert result['total'] == 3
    assert result['importance']['buckets'] == {'关键': 1, '重要': 1, '一般': 0, '未填写或无法识别': 1}
    assert result['duplicates'] == {'groups': 1, 'records': 2}
    assert len(result['anomalies']) == 1
    assert len(result['records']) == 3


def test_missing_sample_and_partial_source_are_not_reported_as_zero():
    broken = table('t8', '网络设备', [['设备名称', '重要程度']],
                   ['第3章 测评对象选择', '网络设备'], 'nested_table')
    payload = build_key_info({'plan': doc('plan', [broken], 'partial')})
    assert count(payload, 'c02', 'sample', 'survey')['status'] == 'missing'
    result = count(payload, 'c02', 'sample', 'plan')
    assert result['status'] == 'unknown'
    assert result['total'] is None


def test_key_info_api_uses_latest_documents_and_project_access():
    from fastapi.testclient import TestClient
    from backend.app import app, password_hash
    from backend.db import Base, Document, Member, Project, Session, User, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session() as db:
            owner = User(username='key-owner', display_name='Owner', password_hash=password_hash('longpassword123'))
            outsider = User(username='key-outsider', display_name='Outsider', password_hash=password_hash('longpassword123'))
            db.add_all([owner, outsider]); db.flush()
            project = Project(name='Synthetic', owner_id=owner.id, config={})
            db.add(project); db.flush()
            db.add(Member(project_id=project.id, user_id=owner.id))
            for version, name in ((1, '旧系统'), (2, '新系统')):
                db.add(Document(project_id=project.id, role='survey', filename=f'v{version}.docx',
                                sha256=str(version) * 64, storage_key=f'v{version}', version=version,
                                status='parsed', parsed={'source_tables': [
                                    table('t1', '等级保护对象基本情况表', [['系统名称', name]])]}))
            db.commit()
            pid = project.id
        client = TestClient(app)
        assert client.get(f'/api/projects/{pid}/key-info').status_code == 401
        login = client.post('/api/login', json={'username': 'key-owner', 'password': 'longpassword123'})
        assert login.status_code == 200
        response = client.get(f'/api/projects/{pid}/key-info')
        assert response.status_code == 200, response.text
        assert source(response.json(), 'system_name', 'survey')['value'] == '新系统'
        outsider_client = TestClient(app)
        assert outsider_client.post('/api/login', json={'username': 'key-outsider', 'password': 'longpassword123'}).status_code == 200
        assert outsider_client.get(f'/api/projects/{pid}/key-info').status_code == 404
    finally:
        Base.metadata.drop_all(engine)
