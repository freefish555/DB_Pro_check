# 附录 D、个人模型与脱敏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用已发布的核查点逐条审核附录 D，所有模型请求先经本地整批脱敏预览与授权，按常规/严格两种口径生成可复核的 A—N 问题宽表。

**Architecture:** 沿用 `Knowledge`、`Run`、`Task`、`Issue`，扩展导入和选择逻辑、Word 编号还原及个人模型档案；在 `backend/ai.py` 的唯一网络出口之前强制构造/校验脱敏请求与请求级授权。模型只输出结构化事实，服务端校验后确定性归类，页面和导出读同一运行快照。

**Tech Stack:** Python 3、python-docx、openpyxl、FastAPI、SQLAlchemy、cryptography、httpx、pytest、React/TypeScript、Node 内置测试器。

**Spec:** `docs/superpowers/specs/2026-10-02-review-platform-redesign-design.md` 第 4、5、5A、7—9 节。

## Global Constraints

- 只处理三份 DOCX；21 份新核查点表格、脱敏字段表和两份真实报告仅作本地验收，不提交仓库。
- 内网和外部模型均须走同一脱敏、整批预览、服务端请求级哈希授权；原文、密钥不得进入模型请求、重试、日志或错误回显。
- 常规与严格只改变描述覆盖阈值；符合性判定、错别字、语病、JSON 校验相同；未知/失败不可当无问题。
- 一条结果记录在问题汇总中只占一行；原 Excel A—M 列和 K 名称保留，新增 N“核查点覆盖不足”。
- 网页显示 AI 候选，默认正式导出仅人工确认；层面→对象首次出现顺序→原文位置排序；质量总分禁用。
- 沿用当前依赖和账号体系，安全关口不为追求最短代码而放宽；每项先红后绿。

## Review Focus

1. 自由文本中的新姓名不能保证自动识别；Task 4 测试未确认请求绝无网络调用。
2. 脱敏请求变更仅使该条授权失效；Task 4 测试相邻未变条继续有效。
3. 模型返回合法 JSON 但虚构引文/重复核查点时不能产生“无问题”；Task 5 覆盖。
4. 标题编号从样式继承而非直接编号时 B 列仍应还原；Task 2 覆盖。
5. 对象原文 A、B、A 交错时结果排序应为 A、A、B，且层面级记录不误判对象丢失；Task 6 覆盖。

## File Map

- `backend/catalog.py`：21 份表的导入、SAG/扩展/电力选择、冲突诊断；`Knowledge.content` 保留不可变来源。
- `backend/documents.py`：附录标题 OOXML 编号及每条记录的真实章节/层面/对象/原文顺序。
- `backend/model_profiles.py`：允许的服务、审核员私有档案和密钥访问；`backend/db.py` 仅加必要表和迁移。
- `backend/redaction.py`：动态请求体脱敏、稳定代号、预览、请求哈希；无网络操作；`backend/db.py` 新增本地加密映射的 `RedactionBatch` 与请求级 `RedactionApproval` 表。
- `backend/ai.py`：共同基础契约、模式覆盖策略、响应校验、唯一模型网络出口。
- `backend/appendix.py`：确定性 J—N 分类、问题实体、行聚合和排序。
- `backend/app.py`：管理员/个人模型接口、预览确认、运行停等、复核、附录 D 查询及导出。
- `frontend/src/main.tsx`, `frontend/src/style.css`：配置、预览、记录审核及 A—N 宽表；`frontend/src/appendixView.ts` 放纯排序/筛选辅助函数。
- `tests/test_catalog_v2.py`, `tests/test_appendix_numbering.py`, `tests/test_model_profiles.py`, `tests/test_redaction.py`, `tests/test_ai_contract.py`, `tests/test_appendix_api.py`, `frontend/tests/appendixView.test.mjs`：合成行为测试；真实案例只作本地验收。

### Task 1: 新核查点导入、选择与冲突诊断

**Files:** Modify `backend/catalog.py`, `backend/app.py`; Test `tests/test_catalog_v2.py`。

**Interfaces:** `import_workbook(data: bytes, filename: str) -> dict` 保存来源工作表/行号、等级、家族、电力类别、SAG、核查点和判定规则；`select_requirements(catalogs: list, config: dict) -> list[dict]` 仅返回当前 S/A/G 与所选扩展，包含 `sources[]`；冲突返回诊断并阻断发布/使用。

- [ ] **Step 1: Write failing tests** `test_s2a3g3_uses_level_two_s_and_level_three_a_g`、`test_power_categories_are_mutually_exclusive`、`test_identical_general_power_point_merges_with_two_sources`、`test_different_rule_is_conflict_not_silent_merge`、`test_missing_rule_remains_visible`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_catalog_v2.py -q`，确认筛选/电力去重行为失败。
- [ ] **Step 3: Implement** 新文件名类别识别、逐行来源、版本化发布与精确去重；对 21 份本地表跑导入诊断，不修补原表文字。
- [ ] **Step 4: Run** 指定测试及全量 pytest；本地核对 21 份导入数、冲突/缺规则清单。
- [ ] **Step 5: Commit** 代码和合成测试。

### Task 2: 附录 D 的真实章节号、对象与源顺序

**Files:** Modify `backend/documents.py`; Test `tests/test_appendix_numbering.py`。

**Interfaces:** `parse_docx` 的 `records[]` 增加 `chapter_number, chapter_status, layer_order, object_order, source_order, object_status, heading_source`；未定位时显式 `待定位`，从不填固定 `APP_D` 当实际章节号。

- [ ] **Step 1: Write failing tests** `test_direct_numbering_resolves_appendix_heading`、`test_style_inherited_numbering_resolves_parent_title`、`test_unresolved_numbering_is_pending`、`test_layer_record_without_object_differs_from_missing_heading`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_appendix_numbering.py -q`，确认新源字段缺失。
- [ ] **Step 3: Implement** 从 `numbering.xml`、段落直接 `numPr` 与样式继承关系按文档顺序维护计数；保留标题和层面/对象位置，不在无对象标题的管理层面伪造对象。
- [ ] **Step 4: Run** 指定测试和全量 pytest；本地两份报告核对 582/831 条、直接/样式继承的附录标题，并列出仍待定位记录。
- [ ] **Step 5: Commit** 解析逻辑与合成测试。

### Task 3: 管理员服务名单与审核员私有模型档案

**Files:** Create `backend/model_profiles.py`; Modify `backend/db.py`, `backend/app.py`; Test `tests/test_model_profiles.py`。

**Interfaces:** `ModelService` 存管理员批准地址/协议/状态；`UserModelProfile` 存所属用户、服务 ID、模型标识、加密密钥、配置版本。`GET/POST/PATCH /api/model-services` 仅管理员写；`GET/POST/PATCH /api/me/model-profiles` 仅本人管理且任何 GET 均不回显明文；运行快照固定发起人/档案/版本/地址/模型。

- [ ] **Step 1: Write failing tests** `test_two_users_cannot_read_or_select_each_others_profile`、`test_unapproved_endpoint_cannot_be_saved`、`test_key_is_not_returned_or_logged`、`test_profile_rotation_blocks_unexecuted_job`、`test_deepseek_compatible_request_uses_selected_model`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_model_profiles.py -q`，确认权限/档案行为缺失。
- [ ] **Step 3: Implement** Fernet 加密与服务端权限检查；连通性仅发送固定合成文本；兼容 DeepSeek/OpenAI Chat Completions 格式，模型列表由管理员配置；已有全局配置只作迁移来源，不再作为新运行的隐式目标。此任务完成时先阻断旧附录 D 运行入口，直至 Task 4 的脱敏授权关口完成。
- [ ] **Step 4: Run** 指定测试、全量 pytest；本地假 HTTP 服务验证请求格式与限流/重试，不发真实报告到外网。
- [ ] **Step 5: Commit** 模型接口、迁移及测试。

### Task 4: 唯一请求出口、整批脱敏预览与请求级放行

**Files:** Create `backend/redaction.py`; Modify `backend/ai.py`, `backend/app.py`, optionally `backend/db.py`; Test `tests/test_redaction.py`。

**Interfaces:** `prepare_model_request(dynamic_payload: dict, project_terms: dict, token_map: dict, context: dict) -> RedactedRequest` 返回最终将发送的 JSON、更新后的稳定代号映射、未确定项、请求哈希；`RedactionBatch` 保存运行/批次版本、加密代号映射与逐请求哈希；`authorize_batch(run_id, hashes, user_id)` 原子保存逐请求 `RedactionApproval` 并将获准任务从 `awaiting_redaction` 转为 `queued`；`assert_authorized(run_id, record_id, current_hash)` 在每次发送/重试之前验证。`context` 必含提示词/知识版本、服务地址和模型配置版本，并进入哈希。

- [ ] **Step 1: Write failing tests** `test_all_dynamic_fields_redact_names_org_phone_address_ip_domain_url_number`、`test_same_value_gets_stable_token_across_batch`、`test_unconfirmed_or_uncertain_request_never_hits_mock_transport`、`test_changed_request_reopens_only_its_approval`、`test_retry_and_error_do_not_leak_original`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_redaction.py -q`，确认网络出口现在直接发送原文。
- [ ] **Step 3: Implement** 用结构化值优先建词典、规则补充自由文本、人工补词重新生成整批预览；序列化后再次扫描最终动态请求体。运行停在待确认，后台只在服务端哈希授权后发信；原文映射留本地，日志/错误脱敏。
- [ ] **Step 4: Run** 指定测试和全量 pytest；用本地假模型截获整批请求逐字段检查零原值。
- [ ] **Step 5: Commit** 安全关口、API 和测试。

### Task 5: AI 结构化契约与确定性问题分类

**Files:** Modify `backend/ai.py`, `backend/app.py`; Create `backend/appendix.py`; Test `tests/test_ai_contract.py`。

**Interfaces:** `evaluate(redacted_request, mode, model_profile) -> dict` 只返回经验证的 `record_id, semantic_alignment, point_results, key_condition_missing, verdict_review, writing`；`classify_appendix(record, requirement, analysis, mode) -> dict` 生成 `issues[]`, `has_issue`, `review_state`, `columns[J..N]`，无网络调用。

- [ ] **Step 1: Write failing tests** `test_regular_allows_noncritical_omission_strict_reports_n`、`test_unrelated_goes_k_without_duplicate_n`、`test_key_condition_goes_n_in_both_modes`、`test_verdict_typo_grammar_same_in_both_modes`、`test_invalid_enum_duplicate_point_fabricated_quote_is_pending`、`test_no_rule_never_becomes_supported`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_ai_contract.py -q`，确认旧 `evaluate` 和归类不满足契约。
- [ ] **Step 3: Implement** 共同基础提示词+版本化覆盖策略；模型内容视为数据，缺失不等于不符合；解析 JSON 并校验引文位于发送的脱敏文本，引用回映到本地证据；`unknown`/失败进入待核实，不产生无问题结论。
- [ ] **Step 4: Run** 指定测试、全量 pytest；用本地假模型模拟空响应、截断和格式错误。
- [ ] **Step 5: Commit** 契约、分类器、测试。

### Task 6: 附录 D A—N 宽表、逐问题复核与导出

**Files:** Modify `backend/app.py`, `frontend/src/main.tsx`, `frontend/src/style.css`; Create `frontend/src/appendixView.ts`; Test `tests/test_appendix_api.py`, `frontend/tests/appendixView.test.mjs`。

**Interfaces:** `GET /api/projects/{pid}/runs/{rid}/appendix?view=issues|all|pending|rejected` 返回按稳定键排列的记录行；单个问题沿用版本化 `Issue` 复核；`GET /api/projects/{pid}/runs/{rid}/appendix/export?view=confirmed|candidates` 返回 A—N 主表和“问题复核明细”。

- [ ] **Step 1: Write failing tests** `test_only_issue_candidates_appear_in_default_web_view`、`test_one_record_multiple_issue_columns_one_row`、`test_confirmed_export_excludes_pending_and_rejected`、`test_interleaved_a_b_a_sorts_a_a_b`、`test_export_prevents_formula_injection`；Node 测试断言筛选和行级 J—N 摘要。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_appendix_api.py -q` 与 `node --test frontend/tests/appendixView.test.mjs`，确认新视图/导出缺失。
- [ ] **Step 3: Implement** 首页/运行配置显示“常规审核/严格审核”；附录 D 全量页与问题汇总页分开；主表固定 A—D、J—N 问题单元格、D 列问题摘要、详情证据、逐问题复核，桌面与窄屏均可用；复用后端同一排序和快照。
- [ ] **Step 4: Run** 两组测试、全量 pytest、`npm --prefix frontend run build`；浏览器验证模式切换、预览授权、汇总/误报/待核实切换、点击证据、导出与行序。
- [ ] **Step 5: Commit** 页面、接口、导出和测试。

## Exit Check

本地 21 表发布/选择、两份真实报告编号与记录数、假模型截获脱敏、个人档案权限、A—N 页面/Excel 对照均通过；任何真实内容、模型密钥及本地代号映射不入公开提交。最后按第三份计划检查高风险和跨模块台账。
