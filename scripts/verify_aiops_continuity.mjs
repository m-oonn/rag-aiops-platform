// Direct JavaScript execution only; no Vue transform or build.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { clockTime, logEvents, evidenceRows, reportActions } from '../frontend/src/lib/diagnosisVisuals.js';
import { getHistory, rememberRun, forgetRun, validRunId, readDraft, writeDraft } from '../frontend/src/lib/history.js';

const storage = () => {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
};

test('history accepts backend IDs, ignores corrupt entries and deduplicates', () => {
  globalThis.localStorage = storage();
  assert.ok(validRunId('a'.repeat(64)));
  assert.ok(!validRunId('a'.repeat(65)));
  localStorage.setItem('aiops:runs:v2:1', JSON.stringify([null, 3, {thread_id:'one'}, {thread_id:'one'}, {thread_id:'bad/id'}]));
  assert.deepEqual(getHistory(1).map(row => row.thread_id), ['one']);
});
test('history reread preserves server time and explicit removal', () => {
  globalThis.localStorage = storage();
  rememberRun(1, {thread_id:'one', updated_at:'2026-11-10T00:00:00Z'});
  rememberRun(1, {thread_id:'one', status:'completed'});
  assert.equal(getHistory(1)[0].updated_at, '2026-11-10T00:00:00Z');
  forgetRun(1, 'one');
  assert.deepEqual(getHistory(1), []);
});
test('drafts are isolated and storage errors do not destroy the form', () => {
  globalThis.sessionStorage = storage();
  writeDraft(1, {query:'故障', terminalEnabled:true});
  assert.equal(readDraft(1).query, '故障');
  assert.equal(readDraft(2), null);
  writeDraft(1, null);
  assert.equal(readDraft(1), null);
  globalThis.sessionStorage = { setItem() { throw Error('quota'); }, getItem() { throw Error('denied'); } };
  assert.doesNotThrow(() => writeDraft(1, {query:'保留'}));
  assert.equal(readDraft(1), null);
});
test('missing timestamps never become epoch times', () => {
  for (const value of [null, undefined, '']) assert.equal(clockTime(value), '—');
});
test('structured log messages remain visible', () => {
  assert.match(logEvents({lines:[JSON.stringify({message:'业务读取失败', level:'ERROR'})]})[0].text, /业务读取失败/);
});
test('corrupt historical evidence cannot crash remaining records', () => {
  assert.equal(evidenceRows([null, 42, {evidence_id:'valid', summary:'可用'}]).length, 1);
});
test('repeated action preserves all safety and verification conditions', () => {
  const rows = reportActions({recommendations:[
    {action:'重启', preconditions:['先备份'], risks:['短暂中断'], verification_steps:['检查入口']},
    {action:'重启', preconditions:['经审批'], risks:['连接断开'], verification_steps:['检查下游']},
  ]});
  assert.deepEqual(rows[0].preconditions, ['先备份', '经审批']);
  assert.deepEqual(rows[0].risks, ['短暂中断', '连接断开']);
  assert.deepEqual(rows[0].verification, ['检查入口', '检查下游']);
});
test('same action for different targets stays separately actionable', () => {
  assert.equal(reportActions({recommendations:[{action:'重启', scope:{service:'a'}}, {action:'重启', scope:{service:'b'}}]}).length, 2);
});
test('damaged recommendation entries do not hide intact actions', () => {
  assert.equal(reportActions({recommendations:[null, {action:'检查入口'}]}).length, 1);
});
