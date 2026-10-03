"""Synthetic coverage for the high-risk four-way review core."""

from backend.checks import _legacy_risk_score, risk_review


def parsed_report(*tables):
    return {"risk_tables": list(tables)}


def table(kind, chapter, source, headers, rows):
    return {
        "kind": kind,
        "chapter": chapter,
        "source": source,
        "headers": headers,
        "rows": rows,
    }


def test_unmatched_problem_analysis_and_hazard_rows_remain():
    report = parsed_report(
        table("problem", "CH03", "problem.docx:T3", ["description", "asset"], [["unmatched problem", "db-2"]]),
        table("overall", "CH04", "problem.docx:T4", ["description", "asset"], [["overall observation", "db-2"]]),
        table("hazard", "CH05", "problem.docx:T5", ["description", "asset"], [["重大风险隐患 row", "db-2"]]),
    )
    result = risk_review(report, [{"key": "g1", "scenario": "a wholly different scenario"}], {"similarity_threshold": 0.95})

    assert len(result["source_rows"]) == 3
    assert {row["kind"] for row in result["source_rows"]} == {"problem", "overall", "hazard"}
    assert len(result["unmatched"]) == 3
    assert all(candidate["status"] == "unmatched" for candidate in result["candidates"])
    assert any(issue["category"] == "major_hazard_table" for issue in result["issues"])


def test_one_problem_has_multiple_candidate_links():
    report = parsed_report(
        table("problem", "CH03", "problem.docx:T3", ["description", "asset"], [["access control weakness", "db-1"]])
    )
    guide = [
        {"key": "g1", "scenario": "access control weakness in a database", "source": "guide:1"},
        {"key": "g2", "scenario": "access control weakness affecting accounts", "source": "guide:2"},
    ]
    result = risk_review(report, guide, {"similarity_threshold": 0.2, "max_candidates": 3})

    links = result["links"]
    assert len(links) == 2
    assert {link["source_row_id"] for link in links} == {result["source_rows"][0]["row_id"]}
    assert all(link["status"] == "candidate" for link in links)
    assert result["candidates"][0]["final_conclusion"] is None


def test_similarity_never_sets_final_high_risk():
    report = parsed_report(
        table("problem", "CH03", "problem.docx:T3", ["description", "asset"], [["weak password", "server-1"]])
    )
    result = risk_review(report, [{"key": "g1", "scenario": "weak password on server", "major": "high-risk"}])

    assert result["links"][0]["machine_conclusion"] is None
    assert result["candidates"][0]["major_hazard_assessment"] == "pending"
    assert result["candidates"][0]["final_conclusion"] is None
    assert result["issues"][0]["machine"]["auto_conclusion"] == "none"


def test_unknown_applicability_stays_pending():
    report = parsed_report(
        table("problem", "CH03", "problem.docx:T3", ["description", "asset"], [["weak password", "server-1"]])
    )
    guide = [{"key": "g1", "scenario": "weak password", "scope": "business continuity or key industry"}]
    result = risk_review(report, guide)

    assert result["applicability"]["g1"] == "pending"
    assert result["guide_rows"][0]["applicability"] == "pending"
    assert result["links"][0]["applicability"] == "pending"


def test_explicit_grade_text_conflict_is_issue():
    report = parsed_report(
        table(
            "risk",
            "CH05",
            "report.docx:T5",
            ["description", "asset", "risk analysis", "risk grade"],
            [["weak password", "server-1", "determined as high risk", "low"]],
        )
    )
    result = risk_review(report, [])

    assert result["conflicts"] == [{
        "type": "grade_conflict",
        "expected": "high",
        "actual": "low",
        "row_id": result["source_rows"][0]["row_id"],
        "source": "report.docx:T5 · 数据行1",
    }]
    assert any(issue["category"] == "risk_consistency" for issue in result["issues"])


def test_legacy_projection_joins_three_report_tables_by_problem_and_guide_requirement():
    report = parsed_report(
        table('problem', 'CH03', 'T3', ['问题编号', '安全问题', '测评对象', '测评项'],
              [['P-1', '未设置访问控制', '服务器甲', 'a）应对登录用户进行身份鉴别']]),
        table('overall', 'CH04', 'T4', ['问题编号', '安全问题', '整体测评描述'],
              [['P-1', '未设置访问控制', '整体影响描述']]),
        table('risk', 'CH05', 'T5', ['问题编号', '安全问题', '危害分析结果', '风险等级'],
              [['P-1', '未设置访问控制', '风险分析描述', '高']]),
    )
    guide = [{'key': 'g1', 'clause': '6.1.1', 'requirement': '应对登录用户进行身份鉴别',
              'scope': '三级', 'scenario': '口令弱', 'mitigation': '增加认证',
              'evaluation': '参考评价', 'major': '高风险项'}]
    result = risk_review(report, guide)

    assert len(result['legacy_rows']) == 1
    row = result['legacy_rows'][0]
    assert row['source_row_id'] == result['source_rows'][0]['row_id']
    assert row['guide_key'] == 'g1'
    assert row['score'] == 100
    assert list(row['values']) == [
        '序号', '问题编号', '报告安全问题描述', '报告4.3整体测评描述', '报告第5章问题风险分析',
        '报告涉及对象', '高风险条款号', '适用范围', '报告判定', '是否重大风险',
        '指引-场景/问题描述', '指引-可能的缓解措施', '指引-风险评价-参考',
    ]
    assert [row['values'][name] for name in ('问题编号', '报告4.3整体测评描述',
           '报告第5章问题风险分析', '高风险条款号', '报告判定', '是否重大风险')] == [
        'P-1', '整体影响描述', '风险分析描述', '6.1.1', '高', '高风险项']


def test_legacy_projection_does_not_match_empty_or_unrelated_requirement():
    report = parsed_report(table('problem', 'CH03', 'T3', ['安全问题', '测评项'],
                                 [['弱口令', ''], ['未授权', '完全不同的要求']]))
    guide = [{'key': 'g1', 'requirement': '应对登录用户进行身份鉴别', 'scenario': '弱口令'}]
    result = risk_review(report, guide)
    assert result['legacy_rows'] == []
    assert len(result['source_rows']) == 2


def test_legacy_projection_keeps_repeated_guide_context_before_excel_merge():
    report = parsed_report(table('problem', 'CH03', 'T3', ['安全问题', '测评项'],
                                 [['问题一', '应进行身份鉴别'], ['问题二', '应进行身份鉴别']]))
    guide = [{'key': 'g1', 'requirement': '应进行身份鉴别',
              'scenario': '身份鉴别失效', 'mitigation': '补充鉴别', 'evaluation': '风险参考'}]
    rows = risk_review(report, guide)['legacy_rows']

    assert len(rows) == 2
    for row in rows:
        assert [row['values'][name] for name in ('指引-场景/问题描述',
               '指引-可能的缓解措施', '指引-风险评价-参考')] == [
            '身份鉴别失效', '补充鉴别', '风险参考']


def test_legacy_similarity_threshold_and_unicode_cleaning():
    assert _legacy_risk_score('安' * 32 + '甲', '安' * 32 + '乙') == 97
    assert _legacy_risk_score('安' * 48 + '甲', '安' * 48 + '乙') == 98
    assert _legacy_risk_score('安' * 66 + '甲', '安' * 66 + '乙') == 99
    assert _legacy_risk_score('abc 甲，乙', '甲乙') == 100
    assert _legacy_risk_score('甲★乙', '甲乙') < 98


def test_legacy_projection_uses_first_near_match_in_overall_and_risk_tables():
    description = '安全问题' * 12 + '甲'
    near_match = '安全问题' * 12 + '乙'
    report = parsed_report(
        table('problem', 'CH03', 'T3', ['安全问题', '测评项'],
              [[description, '应实施身份鉴别']]),
        table('overall', 'CH04', 'T4', ['安全问题', '整体测评描述'],
              [[near_match, '先出现的整体描述'], [description, '后出现的整体描述']]),
        table('risk', 'CH05', 'T5', ['安全问题', '危害分析结果', '风险等级'],
              [[near_match, '先出现的风险分析', '高'], [description, '后出现的风险分析', '中']]),
    )
    guide = [{'key': 'g1', 'requirement': '应实施身份鉴别'}]
    row = risk_review(report, guide)['legacy_rows'][0]['values']

    assert row['报告4.3整体测评描述'] == '先出现的整体描述'
    assert row['报告第5章问题风险分析'] == '先出现的风险分析'
    assert row['报告判定'] == '高'
