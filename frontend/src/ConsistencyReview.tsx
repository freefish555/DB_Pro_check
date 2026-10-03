import { useEffect, useState } from 'react';
import { columnsFor, locationText, sourceDiffers, sourceStatusLabel, visibleRows } from './consistencyView';

type Any = Record<string, any>;
type Props = {
  projectId: string;
  runs: Any[];
  api: (path: string, method?: string, body?: any) => Promise<any>;
  onRefresh: () => Promise<void>;
};
const roleNames: Any = { survey: '调研表', plan: '测评方案', report: '测评报告（基准）' };
const resultNames: Any = {
  consistent: '一致', different: '字段差异', needs_review: '需核实',
  missing_object: '对象缺失', duplicate_key: '重复对象键',
  incomplete: '比对不完整', empty: '空值',
};
const reviewNames: Any = {
  pending: '待复核', confirmed: '确认问题', rejected: '误报', needs_evidence: '需补证',
};
const filterOptions = [
  ['', '全部状态'], ['different', '字段差异'], ['missing_object', '对象缺失'],
  ['duplicate_key', '重复键'], ['incomplete', '比对不完整'],
  ['parse_failed', '解析失败'],
  ['confirmed', '已确认'], ['rejected', '误报'], ['needs_evidence', '需补证'],
];

function cellText(cell: Any | undefined): string {
  if (!cell) return '来源未设';
  if (cell.status === 'value' || cell.status === 'empty') return cell.raw_value || '（空值）';
  return sourceStatusLabel(cell.status);
}

export default function ConsistencyReview({ projectId, runs, api, onRefresh }: Props) {
  const [scope, setScope] = useState('full');
  const [chosenRun, setChosenRun] = useState('');
  const [category, setCategory] = useState('');
  const [status, setStatus] = useState('');
  const [result, setResult] = useState<Any | null>(null);
  const [selection, setSelection] = useState<{ rowId: string; fieldId: string } | null>(null);
  const [reviewStatus, setReviewStatus] = useState('pending');
  const [reviewNote, setReviewNote] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const eligible = runs.filter(run => run.modules?.includes(scope === 'full' ? 'assets_full' : 'assets_sample'));
  const runId = eligible.some(run => run.id === chosenRun) ? chosenRun : eligible[0]?.id || '';
  const roles = scope === 'full' ? ['survey', 'plan', 'report'] : ['plan', 'report'];

  useEffect(() => {
    if (!runId) { setResult(null); return; }
    let active = true;
    setResult(null);
    setError('');
    api(`/projects/${projectId}/runs/${runId}/consistency?scope=${scope}`)
      .then(data => { if (active) setResult(data); })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [projectId, runId, scope, api]);

  const categories: { id: string; label: string; fields: { id: string; label: string }[] }[] = result?.categories || [];
  const categoryId = categories.some(item => item.id === category) ? category : categories[0]?.id || '';
  const fields = columnsFor(categories, categoryId);
  const rows = visibleRows(result?.rows || [], categoryId, status);
  const selectedRow = result?.rows?.find((row: Any) => row.id === selection?.rowId);
  const selectedField = selectedRow?.fields?.[selection?.fieldId || ''];

  function chooseCell(row: Any, field: Any) {
    setSelection({ rowId: row.id, fieldId: field.id });
    setReviewStatus(row.review?.status || 'pending');
    setReviewNote(row.review?.note || '');
  }

  async function reload() {
    const data = await api(`/projects/${projectId}/runs/${runId}/consistency?scope=${scope}`);
    setResult(data);
    setError('');
  }

  async function saveReview() {
    if (!selectedRow) return;
    setBusy(true); setError('');
    try {
      await api(`/projects/${projectId}/runs/${runId}/consistency/${selectedRow.id}`,
        'PATCH', { version: selectedRow.review?.version || 0, status: reviewStatus, note: reviewNote });
      await reload();
    } catch (err: any) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function download(filtered: boolean) {
    if (!runId) return;
    setBusy(true); setError('');
    try {
      const params = new URLSearchParams({ scope });
      if (filtered && categoryId) params.set('category', categoryId);
      if (filtered && status) params.set('status', status);
      const response = await fetch(`/api/projects/${projectId}/runs/${runId}/consistency/export?${params}`, { credentials: 'same-origin' });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || '导出失败');
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = `三文档一致性-${scope}${filtered ? '-筛选' : '-全量'}.xlsx`;
      link.click(); URL.revokeObjectURL(url);
    } catch (err: any) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <>
    <div className="page-heading"><div><span className="eyebrow">CONSISTENCY REVIEW</span>
      <h1>三文档一致性审核</h1><p>按运行快照逐字段对照，人工意见与机器结果分开保存。</p></div></div>
    <div className="consistency-controls panel">
      <div className="segmented" aria-label="对象范围">
        <button className={scope === 'full' ? 'on' : ''} onClick={() => { setScope('full'); setCategory(''); setSelection(null); }}>全对象 · 三文档</button>
        <button className={scope === 'sample' ? 'on' : ''} onClick={() => { setScope('sample'); setCategory(''); setSelection(null); }}>抽选对象 · 方案与报告</button>
      </div>
      <label>审核运行 <select value={runId} onChange={event => { setChosenRun(event.target.value); setSelection(null); }}>
        {eligible.map(run => <option key={run.id} value={run.id}>{new Date(run.created_at * 1000).toLocaleString()} · {run.status}</option>)}
      </select></label>
      <button onClick={async () => { try { await onRefresh(); await reload(); } catch (err: any) { setError(err.message); } }} disabled={!runId}>刷新</button>
      <button onClick={() => download(true)} disabled={!result || busy}>导出当前筛选</button>
      <button onClick={() => download(false)} disabled={!result || busy}>导出完整结果</button>
    </div>
    {!runId && <div className="notice">请先在“审核任务”中运行三文档一致性核查。</div>}
    {error && <div className="alert" role="alert">{error}</div>}
    {result && <>
      {!result.completeness && <div className="hint-warning">本次解析或映射不完整，不能判为全表一致。请检查下方诊断。</div>}
      <div className="consistency-layout">
        <nav className="panel consistency-categories" aria-label="对象类别">
          {categories.map(item => <button key={item.id} className={item.id === categoryId ? 'active' : ''}
            onClick={() => { setCategory(item.id); setSelection(null); }}>
            {item.label}<small>{result.rows.filter((row: Any) => row.category_id === item.id).length}</small>
          </button>)}
        </nav>
        <div className="consistency-main">
          <div className="panel consistency-toolbar">
            <strong>{categories.find(item => item.id === categoryId)?.label || '对象'}</strong>
            <span>{rows.length} 行 · {fields.length} 字段 · {result.issues?.length || 0} 条候选问题</span>
            <label>筛选 <select value={status} onChange={event => { setStatus(event.target.value); setSelection(null); }}>
              {filterOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select></label>
          </div>
          <div className="panel table-panel consistency-scroll">
            <table className="consistency-grid"><thead>
              <tr><th rowSpan={2}>对象名称</th><th rowSpan={2}>结论</th>
                {fields.map(field => <th key={field.id} colSpan={roles.length}
                  className={rows.some((row: Any) => row.fields?.[field.id]?.has_difference) ? 'difference-field' : ''}>{field.label}</th>)}</tr>
              <tr>{fields.flatMap(field => roles.map(role =>
                <th key={`${field.id}-${role}`}>{roleNames[role]}</th>))}</tr>
            </thead><tbody>
              {rows.map((row: Any) => <tr key={row.id}>
                <td><b>{row.original_names?.report?.[0] || row.original_names?.plan?.[0] || row.original_names?.survey?.[0] || row.entity_key}</b>
                  <small>{row.entity_key}</small></td>
                <td><span className={row.status === 'consistent' ? 'badge good' : 'badge warn'}>{resultNames[row.status] || row.status}</span>
                  {row.has_difference && row.incomplete && <small>差异且证据不完整</small>}
                  {row.review && <small>{reviewNames[row.review.status] || row.review.status}</small>}</td>
                {fields.flatMap(field => roles.map(role => {
                  const outcome = row.fields?.[field.id];
                  const cell = outcome?.sources?.[role];
                  return <td key={`${field.id}-${role}`} className={sourceDiffers(outcome, role) ? 'difference-cell' : ''}>
                    <button className="consistency-cell" title={cellText(cell)}
                      aria-label={`${row.entity_key} ${field.label} ${roleNames[role]}：${cellText(cell)}`}
                      onClick={() => chooseCell(row, field)}>
                      <span>{cellText(cell)}</span><small>{sourceStatusLabel(cell?.status || 'missing')}</small>
                    </button>
                  </td>;
                }))}
              </tr>)}
            </tbody></table>
            {!rows.length && <div className="empty"><p>当前筛选下没有对象行；来源表诊断仍需查看。</p></div>}
          </div>
          {result.diagnostics?.length > 0 && <details className="panel consistency-diagnostics"><summary>来源表与解析诊断（{result.diagnostics.length}）</summary>
            {result.diagnostics.map((item: Any, index: number) => <p key={index}>{item.position_id || item.category_id || item.role} · {sourceStatusLabel(item.status)}{item.diagnostic ? ` · ${item.diagnostic}` : ''}</p>)}
          </details>}
        </div>
      </div>
      {selectedRow && selectedField && <section className="panel consistency-detail" aria-live="polite">
        <h2>{selectedRow.entity_key} · {selectedField.label}</h2>
        <p>比较规则：{selectedField.comparison} · 机器结论：{resultNames[selectedField.status] || selectedField.status}
          {selectedField.has_difference ? ' · 有差异' : ''}{selectedField.incomplete ? ' · 证据不完整' : ''}</p>
        <div className="consistency-evidence">{roles.map(role => {
          const cell = selectedField.sources?.[role];
          return <article key={role}><h3>{roleNames[role]} · {sourceStatusLabel(cell?.status || 'missing')}</h3>
            {cell?.status === 'duplicate_key' ? (cell.records || []).map((record: Any, i: number) =>
              <p key={i}>{record?.raw_value ?? '无值'} · {locationText(record?.source)}</p>) :
              <p className="raw-value">{cellText(cell)}</p>}
            <small>{locationText(cell?.source)}</small>
          </article>;
        })}</div>
        {!!selectedField.issue_codes?.length && <p>异常代码：{selectedField.issue_codes.join('、')}</p>}
        <div className="consistency-review"><label>人工结论 <select value={reviewStatus} onChange={event => setReviewStatus(event.target.value)}>
          {Object.entries(reviewNames).map(([value, label]) => <option value={value} key={value}>{String(label)}</option>)}
        </select></label><label>复核意见 <textarea value={reviewNote} onChange={event => setReviewNote(event.target.value)} /></label>
          <button className="primary" disabled={busy} onClick={saveReview}>保存复核</button>
        </div>
      </section>}
    </>}
  </>;
}
