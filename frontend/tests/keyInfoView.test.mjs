import test from 'node:test';
import assert from 'node:assert/strict';
import { countText, fieldText, fieldDiffers, isDocumentSpecificField } from '../src/keyInfoView.ts';

test('document specific fields form a separate expandable section', () => {
  assert.equal(isDocumentSpecificField({ id: 'system_form' }), true);
  assert.equal(isDocumentSpecificField({ id: 'conclusion' }), true);
  assert.equal(isDocumentSpecificField({ id: 'major_hazard_count' }), true);
  assert.equal(isDocumentSpecificField({ id: 'tested_contact' }), false);
});

test('missing and unknown counts never become false zeroes', () => {
  assert.equal(countText({ status: 'missing', total: null }), '未提供');
  assert.equal(countText({ status: 'unknown', total: null }), '无法确定');
  assert.equal(countText({ status: 'value', total: 0 }), '0');
  assert.equal(countText({ status: 'partial', total: 3 }), '已识别 3（不完整）');
  assert.equal(countText({ status: 'not_applicable', total: null }), '不适用');
});

test('same field keeps each document own value and conflict status', () => {
  const field = { sources: {
    survey: { status: 'value', value: '甲单位' },
    plan: { status: 'missing', value: null },
    report: { status: 'conflict', value: '乙单位', candidates: [{ raw_value: '乙单位' }, { raw_value: '丙单位' }] },
  } };
  assert.equal(fieldText(field.sources.plan), '未提供');
  assert.equal(fieldText(field.sources.report), '乙单位');
  assert.equal(fieldDiffers(field, 'survey'), true);
  assert.equal(fieldDiffers(field, 'plan'), true);
  assert.equal(fieldDiffers({ id: 'conclusion', sources: field.sources }, 'survey'), false);
});
