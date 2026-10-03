type Field = { id: string; label: string };
type Category = { id: string; fields: Field[] };
type Row = {
  id: string;
  category_id: string;
  status: string;
  has_difference?: boolean;
  incomplete?: boolean;
  review?: { status: string } | null;
  fields?: Record<string, { sources?: Record<string, { status: string }> }>;
};

const sourceLabels: Record<string, string> = {
  value: '原值', empty: '空值', missing_object: '对象缺失',
  field_undefined: '源表未设字段', field_unmapped: '字段未映射',
  mapping_unresolved: '映射待核实', not_applicable_field: '不适用',
  missing_cell: '单元格缺失', missing: '源表缺失', ambiguous: '源表定位不唯一',
  parse_failed: '解析失败', ambiguous_header: '表头定位不唯一',
  duplicate_key: '重复对象键',
};

export function sourceStatusLabel(status: string): string {
  return sourceLabels[status] || status;
}

export function sourceDiffers(field: { different_sources?: string[] } | undefined, role: string): boolean {
  return field?.different_sources?.includes(role) || false;
}

export function columnsFor(categories: Category[], categoryId: string): Field[] {
  return categories.find(category => category.id === categoryId)?.fields || [];
}

export function locationText(source: Record<string, any> | null): string {
  if (!source) return '无可定位的来源单元格';
  if (Array.isArray(source)) return source.map(locationText).join('；');
  const chapter = (source.chapter_path || []).join(' / ');
  const position = [source.caption || source.table_id,
    source.row == null ? '' : `行 ${source.row}`,
    source.col == null ? '' : `列 ${source.col}`].filter(Boolean).join(' · ');
  const origin = source.source_cell &&
    (source.source_cell.row !== source.row || source.source_cell.col !== source.col)
    ? `；合并来源 ${JSON.stringify(source.source_cell)}` : '';
  return `${chapter ? chapter + ' · ' : ''}${position}${origin}`;
}

export function visibleRows<T extends Row>(rows: T[], categoryId = '', status = ''): T[] {
  return rows.filter(row =>
    (!categoryId || row.category_id === categoryId) &&
    (!status || (status === 'different' ? row.has_difference :
      status === 'incomplete' ? row.incomplete :
      status === 'parse_failed' ? Object.values(row.fields || {}).some(field =>
        Object.values(field.sources || {}).some(cell => cell.status === 'parse_failed')) :
      row.status === status || row.review?.status === status)));
}
