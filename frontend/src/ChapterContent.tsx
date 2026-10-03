type Cell = { row: number; col?: number; column?: number; raw_value?: string };
type SourceTable = { caption?: string; parse_status?: string; cells?: Cell[] };
type Block = {
  id: string;
  type: string;
  text?: string;
  source?: { location?: string };
  table?: SourceTable;
  nested_tables_data?: SourceTable[];
  images?: { location: string }[];
  textboxes?: { location: string; text?: string }[];
  nested_tables?: { location: string }[];
};

function TableCells({ cells = [] }: { cells?: Cell[] }) {
  const rows = [...new Set(cells.map((cell) => cell.row))].sort((a, b) => a - b);
  return cells.length > 0 && <div className="table-scroll"><table><tbody>{rows.map((row) => <tr key={row}>{cells.filter((cell) => cell.row === row).sort((a, b) => (a.col || a.column || 0) - (b.col || b.column || 0)).map((cell, index) => <td key={`${cell.col || cell.column || index}`}>{cell.raw_value || ""}</td>)}</tr>)}</tbody></table></div>;
}

export type ChapterContentData = {
  chapter: string;
  document?: { filename: string; version: number } | null;
  content_status?: string;
  review_status?: string;
  blocks?: Block[];
};

export default function ChapterContent({ data }: { data: ChapterContentData | null }) {
  if (!data) return null;
  return <details className="panel chapter-content">
    <summary>查看本章节报告原文 · {data.blocks?.length || 0} 个内容块</summary>
    <div className="chapter-content-body">
      <p className="muted">{data.document ? `${data.document.filename} · 第 ${data.document.version} 版` : "本批次未关联测评报告"} · 内容：{data.content_status} · 审核：{data.review_status}</p>
      {!data.blocks?.length && <p>本章节尚未提取到正文；请核对报告结构和解析状态。</p>}
      {data.blocks?.map((block) => {
        return <article key={block.id} className="chapter-block">
          <small>{block.source?.location || block.id}</small>
          {block.type === "table" ? <>
            <strong>{block.table?.caption || "表格"}</strong>
            {block.table?.parse_status !== "parsed" && <span className="muted">提取状态：{block.table?.parse_status || "未识别"}</span>}
            <TableCells cells={block.table?.cells} />
            {block.nested_tables_data?.map((table, index) => <details key={index} className="nested-table"><summary>嵌套表 {index + 1} · {table.caption || "原文表格"}</summary><TableCells cells={table.cells} /></details>)}
          </> : <p>{block.text || "（非文本内容）"}</p>}
          {!!block.images?.length && <small>图片 {block.images.length} 处，需对照原件</small>}
          {!!block.textboxes?.length && <small>文本框 {block.textboxes.length} 处，需对照原件</small>}
          {!!block.nested_tables?.length && <small>嵌套表 {block.nested_tables.length} 处，需对照原件</small>}
        </article>;
      })}
    </div>
  </details>;
}
