import test from 'node:test';
import assert from 'node:assert/strict';
import { annualSeries, historyWindow } from '../src/features/dashboard/performanceModel.ts';
const row = (year, month, revenue, partial = false) => ({ year, month, period: `${year}-${String(month).padStart(2, '0')}`, revenue, partial_month: partial });
test('annual total, linear goal and projection share the selected cutoff', () => {
  const data = annualSeries([row(2026, 1, 100), row(2026, 2, 200), row(2026, 3, 900)], '2026-02', 2400);
  assert.equal(data[1].actual, 300);
  assert.equal(data[1].target, 400);
  assert.equal(data[1].projected, 300);
  assert.equal(data[2].actual, null);
  assert.equal(data[2].projected, 450);
  assert.equal(data[11].projected, 1800);
});
test('missing observations and partial months prevent projections', () => {
  assert.equal(annualSeries([row(2026, 2, 20)], '2026-02', null)[1].projected, null);
  assert.equal(annualSeries([row(2026, 1, 20, true)], '2026-01', null)[1].projected, null);
  const gap = annualSeries([row(2026, 1, 20), row(2026, 3, 30)], '2026-03', null);
  assert.equal(gap[1].actual, null);
  assert.equal(gap[2].actual, 50);
  assert.equal(gap[2].incomplete, true);
});
test('zero revenue is valid evidence and absent goal stays absent', () => {
  const data = annualSeries([row(2026, 1, 0)], '2026-01', null);
  assert.equal(data[0].actual, 0);
  assert.equal(data[1].projected, 0);
  assert.equal(data[11].target, null);
});
test('windows respect month/year and never include future periods', () => {
  const months = [row(2025, 12, 1), row(2026, 1, 2), row(2026, 2, 3)];
  assert.equal(historyWindow(months, '2026-01', '12m').length, 2);
  assert.equal(historyWindow(months, '2026-01', 'year').length, 1);
  assert.equal(historyWindow(months, '2026-01', 'all').at(-1).period, '2026-01');
});
