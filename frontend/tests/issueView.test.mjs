import test from 'node:test';
import assert from 'node:assert/strict';
import { visibleIssues, keepVisibleSelection, chapterMatches, activeIssueRunId } from '../src/issueView.ts';

const rows = [
  { id: 'a', chapter: 'CH01', machine: { related_chapters: ['CH05'] }, status: 'pending', title: '首章问题', description: '', object_name: '' },
  { id: 'b', chapter: 'CH05', machine: {}, status: 'confirmed', title: '风险', description: '', object_name: '' },
];

test('selected run must belong to the current project run list', () => {
  const runs = [{ id: 'b-new', status: 'done' }, { id: 'b-old', status: 'done' }];
  assert.equal(activeIssueRunId(runs, 'a-run'), 'b-new');
  assert.equal(activeIssueRunId(runs, 'b-old'), 'b-old');
  assert.equal(activeIssueRunId([], 'a-run'), '');
});

test('one cross-chapter issue is visible in both chapters without a copied id', () => {
  assert.equal(chapterMatches(rows[0], 'CH01'), true);
  assert.equal(chapterMatches(rows[0], 'CH05'), true);
  assert.deepEqual(visibleIssues(rows, 'CH05', 'ALL', '').map(row => row.id), ['a', 'b']);
});

test('bulk selection keeps only explicitly selected visible rows', () => {
  assert.deepEqual(keepVisibleSelection(['a', 'b'], visibleIssues(rows, 'CH05', 'confirmed', '')), ['b']);
  assert.deepEqual(keepVisibleSelection(['a', 'b'], visibleIssues(rows, 'CH01', 'ALL', '')), ['a']);
});
