// Direct JavaScript execution only; no Vue transform or build.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { clockTime, logEvents, evidenceRows, reportActions } from '../frontend/src/lib/diagnosisVisuals.js';
import { getHistory, rememberRun, forgetRun, validRunId, readDraft, writeDraft } from '../frontend/src/lib/history.js';
import * as history from '../frontend/src/lib/history.js';
import { snapshotSteps } from '../frontend/src/lib/diagnosis.js';

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
test('workspace navigation is stored by user and run with validated tabs', () => {
  globalThis.sessionStorage = storage();
  history.writeWorkspace(1, 'run', {tab:'evidence', evidenceId:'e-one', cursorId:'e-two'});
  assert.equal(history.readWorkspace(1, 'run').evidenceId, 'e-one');
  assert.equal(history.readWorkspace(2, 'run'), null);
  assert.equal(history.readWorkspace(1, 'other'), null);
  sessionStorage.setItem('aiops:view:1:bad', '{"tab":"invalid"}');
  assert.equal(history.readWorkspace(1, 'bad'), null);
});
test('repeated executed checks remain distinct in restored progress', () => {
  const steps = snapshotSteps([
    {node:'planner', payload:{plan:['检查日志', '检查依赖']}},
    {node:'executor', payload:{last_step:'检查日志', result_digest:'首次为空'}},
    {node:'replanner', payload:{remaining_plan:['检查依赖', '检查日志']}},
    {node:'executor', payload:{last_step:'检查依赖', result_digest:'连接失败'}},
    {node:'replanner', payload:{remaining_plan:['检查日志']}},
    {node:'executor', payload:{last_step:'检查日志', result_digest:'补查取得日志'}},
  ]);
  assert.equal(steps.length, 3);
  assert.deepEqual(steps.filter(row => row.text === '检查日志').map(row => row.result), ['首次为空', '补查取得日志']);
  assert.equal(steps.filter(row => row.done).length, 3);
});
