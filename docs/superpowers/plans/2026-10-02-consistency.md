# 三文档一致性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从调研表、测评方案、测评报告提取带出处的 12 类/65 字段，生成全对象和抽选对象一致性宽表，并从相同快照导出 Excel。

**Architecture:** `parse_docx` 保存文档顺序、标题树和源单元格；版本化映射按章节路径、父标题、表头签名定位 58 个源表位置；独立的比较函数生成不可变运行输出。FastAPI 复用现有项目、文档、运行和问题表，React 展示 A 宽表与单元格详情。

**Tech Stack:** Python 3、python-docx、FastAPI、SQLAlchemy、openpyxl、pytest、React/TypeScript、Node 内置测试器。

**Spec:** `docs/superpowers/specs/2026-10-02-review-platform-redesign-design.md` 第 1—3、7—9 节。

## Global Constraints

- 第一版仅审核调研表、测评方案、测评报告三份 DOCX；质量总分禁用。
- 使用 `E:/gydl-cxq/Documents/测评报告审核系统平台/三文档一致性审核需求.xlsx` 和本机 `C:/Users/gydl-cxq/Downloads/电力行标梳理/等保测评核查点梳理表格_全套/三文档一致性审查_接续/` 下的 `三文档一致性审核详细设计.md`、`十二类字段来源映射.md`、`字段映射配置.json` 作一手依据；两组真实案例只在本地运行，绝不加入仓库。
- 全对象对照调研表、方案 2.4、报告附录 A；抽选对象只对照方案第 3 章、报告第 2 章。
- 实体键仅移除 Unicode 空白和括号符号，保留括号内文字、大小写、后缀；普通值仅裁掉首尾空白及排版换行；地址保留协议、端口和路径。
- 任何未定位、未解析、重复键或缺源字段均明确显示状态；解析不全不可显示“全表一致”。
- 原件、解析快照、比对运行及人工意见分离；同一运行快照驱动页面和 Excel。
- 沿用已安装依赖；测试遵循先红后绿；不提交真实文档、运行数据和密钥。

## Review Focus

1. 方案第三章的表题仍是“表 2-*”时应识别为抽选表；Task 1 和 Task 2 的测试必须覆盖。
2. 同名但大小写不同的实体必须分成两行；Task 3 覆盖。
3. 重复实体键不能静默择一；Task 3 覆盖。
4. 表缺失与对象缺失不能混为一谈；Task 3/4 覆盖。
5. `=`, `+`, `-`, `@` 开头的原值不能作为公式导出；Task 4 覆盖。
6. 整行“不涉及”说明及有内容但名称空白的行不能当正常资产或静默丢失；Task 2 覆盖。
7. 同一字段可以既有已证实差异又比较不完整；Task 3 覆盖。

## File Map

- `backend/documents.py`：DOCX 的章节路径、表格和原始单元格定位，不承担跨文档判等。
- `backend/consistency_mapping.py`：12 类/65 字段与 58 源表定位配置及校验；映射与解析分离。
- `backend/consistency.py`：严格实体对齐、字段状态和稳定行顺序；替代资产审核路径的 `compare_assets`。
- `backend/app.py`：运行快照、项目权限、比较结果查询/复核/导出接口。
- `backend/db.py`：新增 `ReviewDecision(run_id,row_id,reviewer_id,status,note,version,updated_at)`，以附加记录保存人工意见；新表由现有 `create_all` 创建，不改旧表结构。
- `frontend/src/main.tsx`, `frontend/src/style.css`：宽表、详情与运行过滤；`frontend/src/consistencyView.ts` 放可用 Node 内置测试器检验的纯排序/状态辅助函数。
- `tests/test_consistency.py`, `tests/test_consistency_api.py`, `frontend/tests/consistencyView.test.mjs`：合成行为测试；本地真实案例验收脚本留在忽略目录。

### Task 1: 保存章节树与原始表格证据

**Files:** Modify `backend/documents.py`; Test `tests/test_consistency.py`。

**Interfaces:** `parse_docx(data: bytes, role: str) -> dict` 增加 `source_tables[]`；每张表包含 `table_id, chapter_path, parent_titles, caption, headers, cells[{row,col,raw_label,raw_value,grid_span,v_merge,source_cell}], location, parse_status`，保留旧 `assets/records/risk_tables` 供过渡。`source_cell` 指向合并组起始格，普通空格无继承值。

- [ ] **Step 1: Write failing tests** `test_source_table_keeps_header_cell_and_section_path`、`test_plan_chapter_three_table_two_caption_is_sample_context`、`test_merged_grid_preserves_origin_and_does_not_fill_plain_blank`、`test_nested_table_is_diagnostic_not_asset`；用合成 DOCX 覆盖父标题为第 3 章而表号仍为 2-*、横向/纵向合并及普通空格。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_consistency.py -q`；确认因缺 `source_tables`/章节路径而失败。
- [ ] **Step 3: Implement** 段落和表格按 OOXML 顺序遍历，按 `gridSpan`/`vMerge` 还原逻辑网格并保存物理格与起始来源，嵌套表只记诊断；表号仅写出处；无法判断章节的表不当成资产缺失。
- [ ] **Step 4: Run** 本任务测试及 `& '..\.venv\Scripts\python.exe' -m pytest -q`；全部通过。
- [ ] **Step 5: Commit** 本任务文件，说明源表定位已保留。

### Task 2: 版本化 58 源表/65 字段映射

**Files:** Create `backend/consistency_mapping.py`; Modify `backend/documents.py` only for locator 缺口；Test `tests/test_consistency.py`。

**Interfaces:** `locate_tables(parsed: dict, role: str, scope: str) -> dict` 返回每个映射源表的 `matched|missing|ambiguous|parse_failed`、证据表 ID 和诊断；`extract_cells(parsed: dict, role: str, scope: str) -> list[dict]` 返回类别/实体/字段/原始值/源位置/状态。映射配置有固定 `mapping_version` 和字段 ID；导入适配器把原配置的 `scheme→plan`、`all→full`、`selected→sample`，不改原依据。

- [ ] **Step 1: Write failing tests** `test_mapping_has_12_classes_65_fields_and_58_source_positions`、`test_locator_prefers_chapter_parent_and_headers_over_caption_number`、`test_ambiguous_table_is_not_silently_selected`、`test_not_applicable_explanation_row_is_not_asset`、`test_nonempty_row_without_name_is_parse_issue`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_consistency.py -q`，确认因映射/定位缺失而失败。
- [ ] **Step 3: Implement** 从已核验 `字段映射配置.json` 导入 12 类、65 字段和 58 个逻辑源表位置，再与需求 Excel、来源映射文档逐项核对；生成仅含字段/表头/定位规则的版本化配置，不拷贝案例原值。按章节路径→父标题→表头签名匹配，物理表序号只用于诊断；保留每个原始单元格的来源。
- [ ] **Step 4: Run** 指定测试及全量 pytest；在本地 CP25-0160、CP25-0245 核对 58 个位置并保存不含原文的通过/失败计数，失败清单逐项可查。
- [ ] **Step 5: Commit** 配置、解析器和合成测试，不提交案例数据。

### Task 3: 严格对齐与字段状态

**Files:** Create `backend/consistency.py`; Modify `backend/checks.py` 的资产调用边界；Test `tests/test_consistency.py`。

**Interfaces:** `compare_documents(extracted: dict[str,list[dict]], locations: dict, scope: str) -> dict` 返回 `{mapping_version, scope, rows, issues, diagnostics, completeness}`；`rows[]` 含类别、实体键、三源原名称、逐字段源单元格和结论。

- [ ] **Step 1: Write failing tests** `test_entity_key_preserves_case_and_parenthetical_text`、`test_duplicate_key_retains_both_rows_without_cartesian_product`、`test_missing_object_empty_cell_unmapped_field_and_missing_table_differ`、`test_address_compares_protocol_port_path`、`test_crypto_model_and_certificate_stay_needs_review`、`test_report_baseline_missing_does_not_fall_back_to_plan`、`test_difference_and_incomplete_flags_can_coexist`、`test_three_empty_values_are_equal_but_warn_empty`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_consistency.py -q`，确认旧归一化/字段逻辑导致预期失败。
- [ ] **Step 3: Implement** 来源并集、报告基准、严格键、状态优先级与问题候选；重复键形成含全部原行的异常分组，不做笛卡尔积；每个字段分别记录 `has_difference`, `incomplete`, `issue_codes`，字段映射未解决时 `completeness=false`；不复用旧 `norm()` 对实体或地址判等。
- [ ] **Step 4: Run** 指定测试及全量 pytest；核对每个问题能回溯到原始单元格。
- [ ] **Step 5: Commit** 比较模块与测试。

### Task 4: 运行快照、复核和 Excel 导出

**Files:** Modify `backend/app.py`, optionally `backend/db.py`; Test `tests/test_consistency_api.py`。

**Interfaces:** `GET /api/projects/{pid}/runs/{rid}/consistency?scope=full|sample&category=...&status=...` 返回当前运行固定快照；`PATCH /api/projects/{pid}/runs/{rid}/consistency/{row_id}` 保存 `ReviewDecision`；`GET /api/projects/{pid}/runs/{rid}/consistency/export?scope=...&category=...&status=...` 输出“逐对象逐字段结果”“异常明细”（省略过滤参数即全量）。机器比较结果保存在 `Task.output`。

- [ ] **Step 1: Write failing API tests** `test_new_upload_keeps_old_run_source_versions`、`test_consistency_page_and_export_share_row_ids_and_order`、`test_missing_source_table_disables_all_consistent`、`test_export_has_two_review_sheets_and_filter_label`、`test_export_escapes_formula_prefixes_and_keeps_leading_zero`、`test_review_conflict_returns_409`。
- [ ] **Step 2: Run** `& '..\.venv\Scripts\python.exe' -m pytest tests/test_consistency_api.py -q`，确认新接口/快照语义缺失。
- [ ] **Step 3: Implement** 任务执行改用 `locate_tables → extract_cells → compare_documents`；固定文档/映射/算法版本和创建时间；`ReviewDecision` 只附加人工信息，不改 `Task.output`；导出复用查询过滤和同一转义函数。
- [ ] **Step 4: Run** 指定测试和全量 pytest；旧运行在新上传后仍返回旧结果。
- [ ] **Step 5: Commit** API、必要迁移和测试。

### Task 5: A 宽表、单元格详情与导出交互

**Files:** Modify `frontend/src/main.tsx`, `frontend/src/style.css`; Create `frontend/src/consistencyView.ts`, `frontend/tests/consistencyView.test.mjs`。

**Interfaces:** 前端只读取 Task 4 的运行结果，12 类导航、全/抽选切换、字段×来源双层表头、固定对象/结论列、单元格详情、状态/差异过滤、完整/筛选导出。

- [ ] **Step 1: Write failing Node tests** 对纯 `consistencyView.ts` 辅助函数断言：筛选不改变源结果、来源缺失和字段未设标签不同、同一筛选的可见行 ID 顺序稳定。
- [ ] **Step 2: Run** `node --test frontend/tests/consistencyView.test.mjs`，确认行为尚未实现；再用浏览器记录当前缺失的宽表交互。
- [ ] **Step 3: Implement** A 草图视觉结构，报告子列明确标“基准”；结果/序号/名称冻结，差异来源格黄色、差异字段表头橙色且有文字状态；点击单元格显示三源原文、比较视图、逻辑/物理格及合并来源、判定/复核，未可靠取得 Word 页码时不显示猜测页码；窄屏横向滚动、键盘可操作，不引入新 UI 组件库。
- [ ] **Step 4: Run** Node 测试、`npm --prefix frontend run build`、全量 pytest；浏览器验收全/抽选、详情、导出和异常状态。
- [ ] **Step 5: Commit** 前端与测试。

## Exit Check

两组真实案例的源表清单和全/抽选页面逐项复核；CP25-0245 的原设计给出 58 张源表、615 个表头后物理行、3 个“不涉及”说明行和 612 条有名称来源记录，这些只作该案例的核验基准，不能写成跨模板常数。同一运行的页面/Excel 行 ID、顺序、状态一致；现有 unrelated 的 `README.md` 本地改动不纳入提交。完成后再进入附录 D/脱敏计划，最终整体验收另见第三份计划。
