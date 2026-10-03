import { useEffect, useMemo, useState } from 'react';

type Any = Record<string, any>;
type Props = {
  projectId: string;
  runs: Any[];
  api: (path: string, method?: string, body?: any) => Promise<any>;
  onRefresh?: () => Promise<void>;
};

const issueColumns: { key: string; label: string }[] = [
  { key: 'verdict', label: 'J 判定矛盾' },
  { key: 'unrelated', label: 'K 不相关' },
  { key: 'grammar', label: 'L 语句问题' },
  { key: 'typo', label: 'M 错别字' },
  { key: 'description_coverage', label: 'N 覆盖不足' },
];
const statusLabels: Any = {
  pending: '待复核', confirmed: '确认问题', rejected: '误报',
  needs_evidence: '需补证', resolved: '已解决',
};

function textOf(value: any): string {
  if (Array.isArray(value)) return value.map(textOf).filter(Boolean).join('；');
  if (value == null) return '';
  if (typeof value === 'object') return value.text || value.reason || JSON.stringify(value);
  return String(value);
}

function rowHasIssue(row: Any): boolean {
  return issueColumns.some(column => (row.issues?.[column.key] || []).length > 0);
}

export default function AppendixReview({ projectId, runs, api, onRefresh }: Props) {
  const [runId, setRunId] = useState('');
  const [view, setView] = useState('issues');
  const [layer, setLayer] = useState('');
  const [objectName, setObjectName] = useState('');
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<Any | null>(null);
  const [selected, setSelected] = useState<{ row: Any; column: string } | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<Any | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const eligible = runs.filter(run => run.modules?.includes('appendix_d'));
  const activeRun = eligible.some(run => run.id === runId) ? runId : eligible[0]?.id || '';
  const activeRunRecord = eligible.find(run => run.id === activeRun);
  const canRefreshPreview = Boolean(activeRunRecord && ['awaiting_redaction', 'queued', 'partial'].includes(activeRunRecord.status));

  async function load(run = activeRun, selectedView = view) {
    if (!run) { setResult(null); return; }
    setError('');
    try {
      setResult(await api(`/projects/${projectId}/runs/${run}/appendix?view=${selectedView}`));
    } catch (err: any) { setError(err.message); }
  }

  useEffect(() => { load(); }, [projectId, activeRun, view]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (result?.rows || []).filter((row: Any) =>
      (!layer || row.layer === layer) &&
      (!objectName || row.object === objectName) &&
      (!needle || [row.chapter_number, row.layer, row.object, row.control,
        row.requirement, row.text, row.verdict].join(' ').toLowerCase().includes(needle)));
  }, [result, layer, objectName, query]);
  const layers: string[] = Array.from(new Set((result?.rows || []).map((row: Any) => row.layer).filter(Boolean) as string[]));
  const objects: string[] = Array.from(new Set((result?.rows || []).filter((row: Any) => !layer || row.layer === layer)
    .map((row: Any) => row.object).filter(Boolean) as string[]));

  function chooseIssue(row: Any, column: string) {
    setSelected({ row, column });
    setSelectedIssue((row.issues?.[column] || [])[0] || null);
    setNote(((row.issues?.[column] || [])[0] || {}).note || '');
  }

  async function review(status: string) {
    if (!selectedIssue) return;
    setBusy(true); setError('');
    try {
      const updated = await api(`/projects/${projectId}/issues/${selectedIssue.id}`, 'PATCH', {
        version: selectedIssue.version, status, note,
      });
      setSelectedIssue(updated);
      await load();
      if (onRefresh) await onRefresh();
    } catch (err: any) { setError(err.message); }
    finally { setBusy(false); }
  }

  function exportRows(exportView: 'confirmed' | 'candidates') {
    if (!activeRun) return;
    window.open(`/api/projects/${projectId}/runs/${activeRun}/appendix/export?view=${exportView}`, '_blank');
  }

  async function refreshPreview() {
    if (!activeRun) return;
    setBusy(true); setError('');
    try {
      await api(`/projects/${projectId}/runs/${activeRun}/redaction/refresh`, 'POST', {});
      await load();
    } catch (err: any) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <>
    <div className="panel appendix-toolbar">
      <label>审核运行<select value={activeRun} onChange={event => { setRunId(event.target.value); setSelected(null); }}>
        {eligible.map(run => <option key={run.id} value={run.id}>{new Date(run.created_at * 1000).toLocaleString()} · {run.status}</option>)}
      </select></label>
      <label>视图<select value={view} onChange={event => { setView(event.target.value); setSelected(null); }}>
        <option value="issues">问题候选</option><option value="all">全部记录</option>
        <option value="pending">待复核</option><option value="rejected">误报</option><option value="confirmed">已确认</option>
      </select></label>
      <label>层面<select value={layer} onChange={event => { setLayer(event.target.value); setObjectName(''); }}>
        <option value="">全部层面</option>{layers.map(name => <option key={name} value={name}>{name}</option>)}
      </select></label>
      <label>对象<select value={objectName} onChange={event => setObjectName(event.target.value)}>
        <option value="">全部对象</option>{objects.map(name => <option key={name} value={name}>{name}</option>)}
      </select></label>
      <input aria-label="搜索附录D结果记录" placeholder="搜索记录、测评项或对象" value={query} onChange={event => setQuery(event.target.value)} />
      <button disabled={!canRefreshPreview || busy} onClick={refreshPreview}>重算脱敏预览</button>
      <button disabled={!activeRun} onClick={() => exportRows('candidates')}>导出候选</button>
      <button className="primary" disabled={!activeRun} onClick={() => exportRows('confirmed')}>导出已确认</button>
    </div>
    {error && <div className="alert" role="alert">{error}</div>}
    {!activeRun && <div className="notice">请先在“审核任务”中运行附录 D 审核。</div>}
    {result && <div className="appendix-layout">
      <section className="panel table-panel appendix-table-scroll">
        <table className="data-table appendix-table"><thead><tr>
          {(result.columns || []).map((column: string) => <th key={column}>{column}</th>)}
        </tr></thead><tbody>
          {rows.map((row: Any) => <tr key={row.record_id}>
            <td>{row.number}</td><td>{row.chapter_number || '待定位'}</td><td>{row.layer}</td><td>{row.object}</td>
            <td>{row.control}</td><td>{row.requirement}</td><td className="long-cell">{row.text}</td><td>{row.verdict}</td>
            <td className="long-cell">{textOf(row.points)}</td>
            {issueColumns.map(column => <td key={column.key} className={row.issues?.[column.key]?.length ? 'appendix-issue-cell' : ''}>
              <button className="cell-button" disabled={!row.issues?.[column.key]?.length} onClick={() => chooseIssue(row, column.key)}>
                {textOf((row.issues?.[column.key] || []).map((item: Any) => item.text)) || '—'}
              </button>
            </td>)}
          </tr>)}
        </tbody></table>
        {!rows.length && <div className="empty"><p>当前筛选没有记录。</p></div>}
      </section>
      {selected && <aside className="panel appendix-detail" aria-live="polite">
        <h2>{issueColumns.find(item => item.key === selected.column)?.label}</h2>
        <p className="muted">记录 {selected.row.record_id} · {selected.row.object}</p>
        <h4>结果记录</h4><p className="raw-value">{selected.row.text}</p>
        <h4>问题候选</h4>
        {(selected.row.issues?.[selected.column] || []).map((item: Any) => <button key={item.id} className={`appendix-issue-option ${selectedIssue?.id === item.id ? 'selected' : ''}`} onClick={() => { setSelectedIssue(item); setNote(item.note || ''); }}>
          <b>{statusLabels[item.status] || item.status}</b> · {item.text}
        </button>)}
        {selectedIssue && <>
          <h4>原文证据与理由</h4>
          {(selectedIssue.evidence || []).map((item: Any, index: number) => <div className="evidence" key={index}><small>{item.source || item.role || '来源'}</small><p>{item.quote || item.text || ''}</p></div>)}
          <p>{selectedIssue.description || selectedIssue.text || ''}</p>
          {selectedIssue.suggestion && <><h4>修改建议</h4><p>{selectedIssue.suggestion}</p></>}
          {selectedIssue.machine && <details><summary>机器判定依据</summary><pre>{JSON.stringify(selectedIssue.machine, null, 2)}</pre></details>}
          <label>复核意见<textarea value={note} onChange={event => setNote(event.target.value)} /></label>
          <div className="review-actions">{['confirmed', 'rejected', 'needs_evidence'].map(status => <button key={status} className={status === 'confirmed' ? 'primary' : ''} disabled={busy} onClick={() => review(status)}>{statusLabels[status]}</button>)}</div>
        </>}
      </aside>}
    </div>}
  </>;
}
