export function activeIssueRunId(runs: { id: string; status: string }[], selected: string): string {
  return runs.find(run => run.id === selected)?.id ||
    runs.find(run => ["done", "partial", "running", "queued"].includes(run.status))?.id || "";
}

export function chapterMatches(issue: any, chapter: string): boolean {
  return chapter === "ALL" || issue.chapter === chapter ||
    (issue.machine?.related_chapters || []).includes(chapter);
}

export function visibleIssues(rows: any[], chapter: string, status: string, query: string): any[] {
  const search = query.trim();
  return rows.filter((issue) =>
    chapterMatches(issue, chapter) &&
    (status === "ALL" || issue.status === status) &&
    (!search || `${issue.title} ${issue.description} ${issue.object_name}`.includes(search)),
  );
}

export function keepVisibleSelection(selected: string[], visible: any[]): string[] {
  const ids = new Set(visible.map((issue) => issue.id));
  return selected.filter((id) => ids.has(id));
}
