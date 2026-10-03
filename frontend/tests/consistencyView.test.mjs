import test from 'node:test';
import assert from 'node:assert/strict';
import { visibleRows, sourceStatusLabel, columnsFor, locationText, sourceDiffers } from '../src/consistencyView.ts';

test('filtering keeps source rows unchanged and preserves their order', () => {
  const rows = [
    { id: 'a', category_id: 'c01', status: 'missing_object', has_difference: true },
    { id: 'b', category_id: 'c02', status: 'different', has_difference: true },
    { id: 'c', category_id: 'c01', status: 'different', has_difference: true },
  ];
  assert.deepEqual(visibleRows(rows, 'c01', 'different').map(row => row.id), ['a', 'c']);
  assert.deepEqual(rows.map(row => row.id), ['a', 'b', 'c']);
});

test('missing object and undefined source field have different labels', () => {
  assert.notEqual(sourceStatusLabel('missing_object'), sourceStatusLabel('field_undefined'));
  assert.equal(sourceStatusLabel('missing_object'), '对象缺失');
  assert.equal(sourceStatusLabel('field_undefined'), '源表未设字段');
});

test('category fields keep snapshot order', () => {
  const categories = [
    { id: 'c01', fields: [{ id: 'f2', label: '位置' }, { id: 'f1', label: '名称' }] },
    { id: 'c02', fields: [{ id: 'f3', label: '用途' }] },
  ];
  assert.deepEqual(columnsFor(categories, 'c01').map(field => field.id), ['f2', 'f1']);
});

test('parse failure filter finds a source failure even when the row is incomplete', () => {
  const rows = [{ id: 'a', category_id: 'c01', status: 'incomplete',
    fields: { f1: { sources: { report: { status: 'parse_failed' } } } } }];
  assert.deepEqual(visibleRows(rows, '', 'parse_failed').map(row => row.id), ['a']);
});

test('merged source cells retain their own row and original cell location', () => {
  assert.equal(locationText({ chapter_path: ['第2章'], caption: '合成表', row: 3, col: 2,
    source_cell: { row: 2, col: 2 } }),
    '第2章 · 合成表 · 行 3 · 列 2；合并来源 {"row":2,"col":2}');
});

test('only mismatched source cells are highlighted against the report', () => {
  const field = { has_difference: true, different_sources: ['survey'] };
  assert.equal(sourceDiffers(field, 'survey'), true);
  assert.equal(sourceDiffers(field, 'plan'), false);
  assert.equal(sourceDiffers(field, 'report'), false);
});
