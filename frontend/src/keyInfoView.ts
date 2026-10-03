type Value = { status: string; value?: string | null };

export function isDocumentSpecificField(field: { id?: string }): boolean {
  return ['conclusion', 'major_hazard_count', 'system_form'].includes(field.id || '');
}

export function fieldText(source: Value | undefined): string {
  if (!source || source.status === 'missing') return '未提供';
  if (source.status === 'parse_failed') return '提取失败';
  return source.value?.trim() || (source.status === 'empty' ? '源格为空' : '未提供');
}

export function countText(source: { status: string; total?: number | null } | undefined): string {
  if (!source || source.status === 'missing') return '未提供';
  if (source.status === 'unknown') return '无法确定';
  if (source.status === 'not_applicable') return '不适用';
  if (source.status === 'partial') return `已识别 ${source.total ?? 0}（不完整）`;
  return source.status === 'value' ? String(source.total ?? 0) : '无法确定';
}

export function fieldDiffers(field: { id?: string; sources?: Record<string, Value> }, role: string): boolean {
  if (role === 'report' || isDocumentSpecificField(field)) return false;
  const report = field.sources?.report;
  const source = field.sources?.[role];
  if (!report || !source) return false;
  const reportPresent = ['value', 'empty', 'conflict'].includes(report.status);
  const sourcePresent = ['value', 'empty', 'conflict'].includes(source.status);
  if (reportPresent !== sourcePresent) return true;
  return reportPresent && sourcePresent && (report.value || '').trim() !== (source.value || '').trim();
}
