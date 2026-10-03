# 高风险四方核对与统一问题工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将报告第 3/4/5 章与高风险指引做完整可追溯的四方核对，提供人工结论、网页与 Excel 导出，并让各审核模块进入统一问题工作台。

**Architecture:** 文档解析保留第 3/4/5 章所有原始表行；`risk_review` 只提出一对多关联候选和明确文字/等级冲突，不自动定高风险。人工链接和结论附加保存，统一工作台聚合已有 `Issue`、一致性行和附录 D 问题，模块/章节导航中未配置规则明确标记。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy、openpyxl、pytest、React/TypeScript、Node 内置测试器。

**Spec:** `docs/superpowers/specs/2026-10-02-review-platform-redesign-design.md` 第 6—9 节；先执行同日的一致性及附录 D 两份计划，使其结果接口可用。

## Global Constraints

- 指引相似度只排序候选；未知适用性保留待人工核实，只有明确不适用才排除；最终高风险/重大风险结论由审核员确认。
- 第 3、4、5 章和指引每条原始行均可找回，包括无匹配项；页面与 Excel 读取同一运行快照。
- 三份 DOCX 是业务输入；指引 XLSX 是管理员发布的知识，不要求用户上传其他业务材料。
- 问题工作台按模块→章节→问题→证据/复核展示，未配置规则为“未配置”；总分继续禁用。
- 已有真实案例、指引原件和运行数据只在本地验证；不进公开仓库。先红后绿，沿用现有依赖。

## Review Focus

1. 无任何匹配的第 3/4/5 章行仍须出现；Task 2 覆盖。
2. 一条问题可关联多条分析/指引，不能强行一对一；Task 2 覆盖。
3. “关键行业”等仅靠三份文档无法判断时保留待核实；Task 2 覆盖。
4. 页面上改人工意见不能重写源行或机器分数；Task 3 覆盖。
5. 新运行不能自动关闭旧运行问题；Task 4 覆盖。

## File Map

- `backend/catalog.py`：高风险指引导入、分组标题诊断、适用条件字段。
- `backend/documents.py`：报告 3/4/5 章所有相关表行保留来源行 ID 与原值。
- `backend/checks.py`：四方链接、候选与明确冲突；不做最终风险判定。
- `backend/app.py`：运行输出、人工关联和结论、四方页面/导出、跨模块问题列表。
- `backend/db.py`：新增 `RiskReviewDecision(run_id,link_id,reviewer_id,status,conclusion,reason,version,updated_at)`，与机器输出分离；新表由现有 `create_all` 创建。
- `frontend/src/main.tsx`, `frontend/src/style.css`：四方对照页面和统一问题导航；`frontend/src/riskView.ts` 用于纯筛选辅助函数。
- `tests/test_risk_workbench.py`, `tests/test_workbench_api.py`, `frontend/tests/riskView.test.mjs`：合成测试；真实案例验收留本地。

### Task 1: 指引和报告风险源行完整导入

**Files:** Modify `backend/catalog.py`, `backend/documents.py`; Test `tests/test_risk_workbench.py`。

**Interfaces:** `import_guide(wb) -> dict` 返回 `requirements[]` 与分组标题/空行诊断；`parse_docx(report).risk_tables[]` 的每行增加稳定 `row_id, chapter, table_location, row_number, raw_values, parse_status`。

- [ ] **Step 1: Write failing tests** `test_guide_group_title_is_diagnostic_not_rule`、`test_all_chapter_three_four_five_rows_have_locator`、`test_unparsed_risk_table_reports_diagnostic`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_risk_workbench.py -q`，确认现有导入/定位未满足。
- [ ] **Step 3: Implement** 保留有用的原始列和值，指引的条件、缓解、评价、重大标记及出处不丢失；不通过相似度或表头猜测删除源行。
- [ ] **Step 4: Run** 指定测试及全量 pytest；本地指引核对 111 条实质规则和 2 条分组标题诊断。
- [ ] **Step 5: Commit** 导入器、解析器和合成测试。

### Task 2: 四方候选关联和冲突

**Files:** Modify `backend/checks.py`; Test `tests/test_risk_workbench.py`。

**Interfaces:** `risk_review(parsed: dict, guide: list[dict], config: dict) -> dict` 返回每个第 3/4/5 章源行、指引行、候选关联 `links[]`、未匹配清单、明确冲突、适用状态；一个源行可对应多个候选。

- [ ] **Step 1: Write failing tests** `test_unmatched_problem_analysis_and_hazard_rows_remain`、`test_one_problem_has_multiple_candidate_links`、`test_similarity_never_sets_final_high_risk`、`test_unknown_applicability_stays_pending`、`test_explicit_grade_text_conflict_is_issue`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_risk_workbench.py -q`，确认旧 `risk_review` 的遗失/状态问题。
- [ ] **Step 3: Implement** 用相似度只产生排序建议，按原源行 ID 和类别保留所有四方行；明确不适用才排除，无法从文档核实的条件保留候选；自动问题仅限可引用的文字/等级矛盾。
- [ ] **Step 4: Run** 指定测试和全量 pytest；手工抽查两个真实案例的未匹配和多关联样本。
- [ ] **Step 5: Commit** 四方核对与测试。

### Task 3: 人工结论、四方页面和 Excel

**Files:** Modify `backend/app.py`, optionally `backend/db.py`, `frontend/src/main.tsx`, `frontend/src/style.css`; Create `frontend/src/riskView.ts`; Test `tests/test_workbench_api.py`, `frontend/tests/riskView.test.mjs`。

**Interfaces:** `GET /api/projects/{pid}/runs/{rid}/risk` 返回完整源行/候选/人工意见；`PATCH /api/projects/{pid}/runs/{rid}/risk/{link_id}` 以版本号保存 `RiskReviewDecision` 的人工关联、适用性、最终结论和理由；`GET /api/projects/{pid}/runs/{rid}/risk/export` 输出同一快照的四方明细。

- [ ] **Step 1: Write failing tests** `test_risk_api_returns_all_source_and_unmatched_rows`、`test_review_changes_opinion_not_machine_evidence`、`test_risk_excel_and_page_have_same_row_ids`、`test_review_conflict_returns_409`；Node 测试锁定未知适用性与未匹配筛选。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_workbench_api.py -q` 和 `node --test frontend/tests/riskView.test.mjs`，确认接口/筛选缺失。
- [ ] **Step 3: Implement** 第 3 章问题、第 4 章整体测评、第 5 章风险分析/重大隐患、指引四方对照与原文详情；人工可确认一对多关系及结论，导出保留未匹配与状态，不把分数当结论。
- [ ] **Step 4: Run** 指定测试、全量 pytest、前端构建；浏览器核对四方详情和导出行数。
- [ ] **Step 5: Commit** 页面、API、必要迁移和测试。

### Task 4: 统一问题工作台与最终验收

**Files:** Modify `backend/app.py`, `frontend/src/main.tsx`, `frontend/src/style.css`, `README.md`（仅在先核对现有改动后择需修改）；Test `tests/test_workbench_api.py`。

**Interfaces:** 现有 `/api/projects/{pid}/issues` 保留兼容，增加当前 `run_id` 与模块过滤；工作台第一层模块，第二层章节，左列表，右证据/规则/复核；未配置章节明确显示“未配置”；现有 Word/Excel 问题导出继续可用且按当前运行及复核状态。

- [ ] **Step 1: Write failing tests** `test_issue_filter_is_bound_to_run_and_module`、`test_unconfigured_chapter_is_not_zero_issues`、`test_new_run_keeps_old_issue_decisions`、`test_export_defaults_to_confirmed_current_run`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_workbench_api.py -q`，确认当前问题列表/导出跨运行混合。
- [ ] **Step 3: Implement** 复用各模块已有证据详情，调整导航与视觉层次；保持章节占位、权限校验和复核审计；窄屏详情下移、宽表横向滚动、键盘可用、文字和颜色双状态。
- [ ] **Step 4: Run** 全量 pytest、`npm --prefix frontend run build`、假模型端到端和浏览器逐模块验收；逐项核对设计规格第 8 节十个验收门槛及两组本地真实案例。清理任何含敏感信息的测试产物。
- [ ] **Step 5: Commit** 整合代码与非敏感文档。由独立代码审查者做全分支复核，解决重要问题后再依照已获用户授权提交源码到 `freefish555/DB_Pro_check`；核对远端提交和仓库文件清单不含原件、核查点 Excel、密钥或运行数据。

## Exit Check

整体验收依据是运行中的页面/导出、合成自动测试、本地真实案例、假模型截获和全分支审查；仅全量 pytest 或前端构建通过不足以宣布目标完成。
