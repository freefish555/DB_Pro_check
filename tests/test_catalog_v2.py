import io

import pytest
from openpyxl import Workbook

from backend.catalog import import_workbook, select_requirements


def workbook(filename, rows):
    book = Workbook()
    sheet = book.active
    sheet.title = '安全通信网络'
    sheet.append(['序号', '控制点', 'SAG属性标识', '测评项', '核查点数', '核查点', '判定规则'])
    for number, sag, item, point, rule in rows:
        sheet.append([number, '网络架构', sag, item, 1, f'1）{point}', rule])
    data = io.BytesIO()
    book.save(data)
    return import_workbook(data.getvalue(), filename)


def catalog(index, filename, rows):
    content = workbook(filename, rows)
    return {'id': str(index), 'family': content['family'], 'level': content['level'],
            'profile': content['profile'], 'content': content}


def test_s2a3g3_uses_level_two_s_and_level_three_a_g():
    low = catalog(1, '安全通用要求_二级_核查点梳理统计表格.xlsx',
                  [(1, 'S', '身份鉴别', '二级 S 点', '规则 S'), (2, 'A', '访问控制', '二级 A 点', '规则 A')])
    high = catalog(2, '安全通用要求_三级_核查点梳理统计表格.xlsx',
                   [(1, 'S', '身份鉴别', '三级 S 点', '规则 S'), (2, 'A', '访问控制', '三级 A 点', '规则 A'),
                    (3, 'G', '安全审计', '三级 G 点', '规则 G')])
    result = select_requirements([low, high], {'s': 2, 'a': 3, 'g': 3, 'extensions': []})
    assert [r['points'][0]['text'] for r in result] == ['二级 S 点', '三级 A 点', '三级 G 点']


def test_power_categories_are_mutually_exclusive():
    monitor = catalog(1, '电力监控系统安全要求_三级_核查点梳理统计表格.xlsx',
                      [(1, 'G', '身份鉴别', '监控系统点', '规则')])
    management = catalog(2, '电力管理信息系统安全要求_三级_核查点梳理统计表格.xlsx',
                         [(1, 'G', '身份鉴别', '管理信息系统点', '规则')])
    assert monitor['family'] != management['family']
    chosen = select_requirements([monitor, management],
                                 {'s': 3, 'a': 3, 'g': 3, 'extensions': [], 'power_category': 'power_monitoring'})
    assert [r['points'][0]['text'] for r in chosen] == ['监控系统点']
    with pytest.raises(ValueError, match='电力'):
        select_requirements([monitor, management],
                            {'s': 3, 'a': 3, 'g': 3, 'extensions': ['power_monitoring', 'power_management']})


def test_identical_general_power_point_merges_with_two_sources():
    name = '应保证关键网络设备业务处理能力'
    row = [(1, 'G', name, '检查设备容量', '满足为符合')]
    general = catalog(1, '安全通用要求_三级_核查点梳理统计表格.xlsx', row)
    power = catalog(2, '电力监控系统安全要求_三级_核查点梳理统计表格.xlsx', row)
    result = select_requirements([general, power],
                                 {'s': 3, 'a': 3, 'g': 3, 'extensions': [], 'power_category': 'power_monitoring'})
    assert len(result) == 1
    assert len(result[0]['sources']) == 2
    assert len(result[0]['points']) == 1
    assert len(result[0]['points'][0]['sources']) == 2


def test_different_rule_is_conflict_not_silent_merge():
    name = '应保证关键网络设备业务处理能力'
    general = catalog(1, '安全通用要求_三级_核查点梳理统计表格.xlsx',
                      [(1, 'G', name, '检查设备容量', '满足为符合')])
    power = catalog(2, '电力监控系统安全要求_三级_核查点梳理统计表格.xlsx',
                    [(1, 'G', name, '检查设备容量', '不满足为符合')])
    with pytest.raises(ValueError, match='判定规则冲突'):
        select_requirements([general, power],
                            {'s': 3, 'a': 3, 'g': 3, 'extensions': [], 'power_category': 'power_monitoring'})


def test_missing_rule_remains_visible():
    source = catalog(1, '安全通用要求_三级_核查点梳理统计表格.xlsx',
                     [(1, 'G', '身份鉴别', '检查身份标识', '')])
    chosen = select_requirements([source], {'s': 3, 'a': 3, 'g': 3, 'extensions': []})
    assert len(chosen) == 1
    assert chosen[0]['decision'] == ''
    assert '缺少判定规则，仅可检查描述覆盖' in chosen[0]['warnings']
