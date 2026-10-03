import { useEffect, useState } from 'react';
import { countText, fieldDiffers, fieldText, isDocumentSpecificField } from './keyInfoView';

type Any = Record<string, any>;
const roles = [['survey', '调研表'], ['plan', '测评方案'], ['report', '测评报告（基准）']];
const groupNames: Record<string, string> = {
  object: '测评对象', assessed_unit: '被测单位', assessor: '测评单位',
  review: '测评结论与隐患', other: '其他信息',
};

export default function KeyInformation({ projectId, api }: { projectId: string; api: (path: string) => Promise<Any> }) {
  const [data, setData] = useState<Any | null>(null);
  const [scope, setScope] = useState('full');
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setData(null); setError('');
    api(`/projects/${projectId}/key-info`).then(value => { if (active) setData(value); })
      .catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [projectId, api]);

  const fields: Any[] = data?.fields || [];
  const groups = [...new Set(fields.map(field => field.group || 'other'))];
  const counts: Any[] = (data?.counts || []).filter((row: Any) => row.scope === scope);
  const renderGroup = (group: string, rows: Any[]) => rows.length ? <section className="panel key-section" key={group}>
        <h2>{groupNames[group] || group}</h2>
        <div className="key-scroll"><table className="key-grid"><thead><tr><th>字段</th>{roles.map(([role, label]) => <th key={role}>{label}</th>)}</tr></thead>
          <tbody>{rows.map(field => <tr key={field.id}>
            <th scope="row">{field.label}</th>{roles.map(([role]) => {
              const source = field.sources?.[role];
              return <td key={role} className={fieldDiffers(field, role) ? 'key-different' : ''}>
                <div className="key-value">{fieldText(source)}</div>
                <small>{({ value: '已提取', empty: '源格为空', missing: '未提供', conflict: '同文档冲突', parse_failed: '提取失败' } as Any)[source?.status] || source?.status || '未提供'}</small>
                {!!source?.candidates?.length && <details><summary>查看 {source.candidates.length} 处来源</summary>
                  {source.candidates.map((candidate: Any, index: number) => <p key={index}>
                    {candidate.label ? `${candidate.label}：` : ''}{candidate.value || '（空）'}<br />
                    <small>{candidate.source?.chapter_path?.join(' / ') || candidate.source?.location || candidate.source?.table_id || '来源待定位'}
                      {candidate.source?.row ? ` · 行 ${candidate.source.row}` : ''}</small>
                  </p>)}
                </details>}
              </td>;
            })}</tr>)}</tbody></table></div>
      </section> : null;
  return <>
    <div className="page-heading"><div><span className="eyebrow">KEY INFORMATION</span>
      <h1>三文档关键信息</h1><p>同一字段并排查看原值与出处；缺失的材料保留空白状态，不从其他文档补填。</p></div></div>
    {error && <div className="alert" role="alert">{error}</div>}
    {!data && !error && <section className="panel">正在提取关键信息…</section>}
    {data && <>
      {groups.map(group => renderGroup(group, fields.filter(field => (field.group || 'other') === group && !isDocumentSpecificField(field))))}
      <details className="panel key-section"><summary>文档独有信息 · 定级对象形态、测评结论与重大隐患数量</summary>
        <p>保留每份材料实际提供的内容，其他材料缺失不作为同字段差异。</p>
        {groups.map(group => renderGroup(group, fields.filter(field => (field.group || 'other') === group && isDocumentSpecificField(field))))}
      </details>
      <section className="panel key-section">
        <div className="section-title"><div><h2>十二类清单数量</h2><p>统计有效来源条目，不累加“台/套”数量列。重复记录照计并单列提示。</p></div>
          <div className="segmented" aria-label="数量范围"><button className={scope === 'full' ? 'on' : ''} onClick={() => setScope('full')}>全对象</button><button className={scope === 'sample' ? 'on' : ''} onClick={() => setScope('sample')}>抽选对象</button></div></div>
        <div className="key-scroll"><table className="key-grid"><thead><tr><th>类别</th>{roles.map(([role, label]) => <th key={role}>{label}</th>)}</tr></thead><tbody>
          {counts.map(row => <tr key={row.category_id}><th scope="row">{row.label}</th>{roles.map(([role]) => {
            const source = row.sources?.[role];
            const importance = source?.importance || {};
            const buckets = importance.buckets || {};
            return <td key={role}><b>{countText(source)}</b>
              {source?.status === 'value' || source?.status === 'partial' ? <div className="key-count-detail">
                {importance.status === 'field_undefined' ? '重要程度：未设字段' : `关键 ${buckets['关键'] || 0} · 重要 ${buckets['重要'] || 0} · 一般 ${buckets['一般'] || 0} · 未识别 ${buckets['未填写或无法识别'] || 0}`}
                {(source.duplicates?.records || 0) > 0 && <span> · 重复 {source.duplicates.records}</span>}
                {(source.anomalies?.length || 0) > 0 && <span> · 异常 {source.anomalies.length}</span>}
              </div> : null}
              {!!source?.records?.length && <details><summary>查看 {source.records.length} 条来源记录</summary>{source.records.map((record: Any, index: number) => <p key={index}>{record.name || '名称待定位'} · {record.source?.table_id || record.source || ''}</p>)}</details>}
            </td>;
          })}</tr>)}
        </tbody></table></div>
      </section>
    </>}
  </>;
}
