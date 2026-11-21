// Direct JavaScript execution only; no Vue transform or build.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { clockTime, logEvents, evidenceRows, reportActions, visualCandidates, reportFacts, reportOverview, reportQuestions } from '../frontend/src/lib/diagnosisVisuals.js';
import { getHistory, rememberRun, forgetRun, validRunId, readDraft, writeDraft } from '../frontend/src/lib/history.js';
import * as history from '../frontend/src/lib/history.js';
import { snapshotSteps, advanceSteps } from '../frontend/src/lib/diagnosis.js';
import { request, stream } from '../frontend/src/lib/api.js';

const storage = () => {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
};

test('a late unauthorized read cannot log out a newer AIOps identity', async () => {
  globalThis.localStorage = storage();
  localStorage.setItem('token', 'old-token');
  const originalFetch = globalThis.fetch, originalWindow = globalThis.window;
  let respond, expired = 0;
  globalThis.window = {dispatchEvent() {expired++;}};
  globalThis.fetch = () => new Promise(resolve => {respond = resolve;});
  try {
    const pending = request('/aiops/runs/old-run');
    localStorage.setItem('token', 'new-token');
    respond({ok:false, status:401, json:async () => ({detail:'expired'})});
    await assert.rejects(pending, {status:401});
    assert.equal(localStorage.getItem('token'), 'new-token');
    assert.equal(expired, 0);
  } finally {globalThis.fetch = originalFetch; globalThis.window = originalWindow;}
});

test('an unauthorized read still expires its own active AIOps session', async () => {
  globalThis.localStorage = storage();
  localStorage.setItem('token', 'current-token');
  const originalFetch = globalThis.fetch, originalWindow = globalThis.window;
  let expired = 0;
  globalThis.window = {dispatchEvent() {expired++;}};
  globalThis.fetch = async () => ({ok:false, status:401, json:async () => ({detail:'expired'})});
  try {
    await assert.rejects(request('/aiops/runs/current-run'), {status:401});
    assert.equal(localStorage.getItem('token'), null);
    assert.equal(expired, 1);
  } finally {globalThis.fetch = originalFetch; globalThis.window = originalWindow;}
});

test('damaged structured history preserves valid candidates and findings', () => {
  const diagnosis = {kind:'confirmed_cause', hypothesis_id:'h1', alternatives:[null, {hypothesis_id:'h1'}],
    evidence:[null, {evidence_id:'e1'}], observed_findings:[null, {evidence_id:'e1', summary:'入口失败'}]};
  const rows = visualCandidates({candidates:[null, {id:'h1', explanation:'连接失败', evidence_ids:'bad'}],
    candidate_check_progress:{h1:[null, {evidence_ids:['e2']}]}}, diagnosis);
  assert.deepEqual(rows[0].evidence, ['e1', 'e2']);
  assert.equal(reportFacts(diagnosis)[0].text, '入口失败');
  assert.doesNotThrow(() => reportOverview(diagnosis));
});

test('non-list historical report fields are ignored without hiding valid material', () => {
  assert.deepEqual(visualCandidates({candidates:{damaged:true}}, {alternatives:[{hypothesis_id:'h2', explanation:'待验证'}]}).map(row => row.id), ['h2']);
  assert.deepEqual(reportFacts({observed_findings:{}}), []);
  assert.deepEqual(reportActions({recommendations:{}}), []);
  const actions = reportActions({recommendations:[{action:'检查', evidence:[null, {evidence_id:'e1'}], preconditions:'bad', risks:{}, verification_steps:42}]});
  assert.deepEqual(actions[0].evidence, ['e1']);
  assert.deepEqual(actions[0].preconditions, []);
  assert.deepEqual(reportQuestions({unresolved_questions:[null, 12, {question:42}, '真实问题'],
    alternatives:[null, {explanation:'真实问题', critical:false, noncritical_reason:'保留范围边界'}]}),
    [{id:undefined, text:'真实问题', reason:'保留范围边界'}]);
  assert.deepEqual(reportQuestions({unresolved_questions:{}}), []);
});

test('experience drafts survive reread and bind the reviewer, run and candidate revision', () => {
  globalThis.sessionStorage = storage();
  const candidate = {id:'xp-one', version:1, status:'pending'};
  const draft = {kbId:'901', note:'核对后再发布'};
  history.writeExperienceDraft(7, 'saved-run', candidate, draft);
  assert.deepEqual(history.readExperienceDraft(7, 'saved-run', {...candidate}), draft);
  for (const [user, run, item] of [[8, 'saved-run', candidate], [7, 'other-run', candidate],
    [7, 'saved-run', {...candidate, version:2}], [7, 'saved-run', {...candidate, id:'xp-two'}],
    [7, 'saved-run', {...candidate, status:'published'}]]) {
    assert.equal(history.readExperienceDraft(user, run, item), null);
  }
  history.writeExperienceDraft(7, 'saved-run', candidate, null);
  assert.equal(history.readExperienceDraft(7, 'saved-run', candidate), null);
  globalThis.sessionStorage = {setItem() {throw Error('quota');}, getItem() {throw Error('denied');}};
  assert.doesNotThrow(() => history.writeExperienceDraft(7, 'saved-run', candidate, draft));
  assert.equal(history.readExperienceDraft(7, 'saved-run', candidate), null);
});

test('approved terminal checks stay complete after replay reload', () => {
  const rows = snapshotSteps([
    {node:'planner', payload:{plan:['检查服务', '检查入口']}},
    {node:'executor', payload:{}},
    {node:'terminal_review', payload:{last_step:'检查服务', result_digest:'服务正常'}},
  ]);
  assert.deepEqual(rows.map(row => [row.text, row.done]), [['检查服务', true], ['检查入口', false]]);
  assert.equal(rows[0].result, '服务正常');
});

test('parallel batch completes both planned checks and survives snapshot reread', () => {
  const plan = {node:'planner', payload:{plan:['[并行] 检查端口', '[并行] 检查进程', '检查日志']}};
  const batch = {node:'executor', payload:{last_step:'检查进程', completed_steps:[
    {last_step:'检查端口', result_digest:'端口关闭'},
    {last_step:'检查进程', result_digest:'进程不存在'},
  ]}};
  const reread = snapshotSteps([plan, batch]);
  assert.deepEqual(reread.map(row => [row.text, row.done, row.result]), [
    ['检查端口', true, '端口关闭'], ['检查进程', true, '进程不存在'], ['检查日志', false, ''],
  ]);
  assert.deepEqual(advanceSteps(advanceSteps([], plan), batch), reread);
  const repeated = snapshotSteps([plan, {...batch, payload:{completed_steps:[
    {last_step:'检查端口', result_digest:'首轮'}, {last_step:'检查端口', result_digest:'复查'},
  ]}}]);
  assert.equal(repeated.filter(row => row.text === '检查端口' && row.done).length, 2);
});

test('history accepts backend IDs, ignores corrupt entries and deduplicates', () => {
  globalThis.localStorage = storage();
  assert.ok(validRunId('a'.repeat(64)));
  assert.ok(!validRunId('a'.repeat(65)));
  localStorage.setItem('aiops:runs:v2:1', JSON.stringify([null, 3, {thread_id:'one'}, {thread_id:'one'}, {thread_id:'bad/id'}]));
  assert.deepEqual(getHistory(1).map(row => row.thread_id), ['one']);
});
test('server history restores missing browser entries and keeps cached details', () => {
  const local = [{thread_id:'cached', query:'本机草稿', diagnosis:{kind:'localized_fault'}, updated_at:'2026-11-18T10:00:00Z'}];
  const merged = history.mergeHistoryList(local, [
    {thread_id:'server-run', query:'服务器记录', status:'completed', updated_at:'2026-11-18T12:00:00Z'},
    {thread_id:'cached', query:'本机草稿', status:'completed', updated_at:'2026-11-18T11:00:00Z'},
    {thread_id:'server-run', query:'重复行', status:'failed'},
    {thread_id:'../foreign', query:'非法编号'},
  ], 1);
  assert.deepEqual(merged.map(row => row.thread_id), ['server-run', 'cached']);
  assert.equal(merged[1].diagnosis.kind, 'localized_fault');
  assert.equal(merged[1].status, 'completed');
});
test('history can merge later server pages without truncating earlier records', () => {
  globalThis.localStorage = storage();
  const page = (start, end, time) => Array.from({length:end - start}, (_, index) => ({
    thread_id:`run-${start + index}`, query:`故障 ${start + index}`, updated_at:time,
  }));
  const firstPage = history.mergeHistoryList([], page(0, 100, '2026-11-10T00:00:00Z'), 1);
  const allPages = history.mergeHistoryList(firstPage, page(100, 200, '2026-11-11T00:00:00Z'), 1, 200);
  assert.equal(allPages.length, 200);
  assert.ok(allPages.some(row => row.thread_id === 'run-0'));
  assert.ok(allPages.some(row => row.thread_id === 'run-199'));
});
test('browser-removed runs stay hidden when server history is refreshed', () => {
  globalThis.localStorage = storage();
  history.forgetRun(1, 'hidden-run');
  history.rememberRun(1, {thread_id:'hidden-run', query:'已移除'});
  assert.deepEqual(history.getHistory(1), []);
  assert.deepEqual(history.mergeHistoryList([], [
    {thread_id:'hidden-run', query:'已移除', status:'completed'},
  ], 1), []);
  assert.equal(history.mergeHistoryList([], [
    {thread_id:'hidden-run', query:'其他用户可见', status:'completed'},
  ], 2).length, 1);
});
test('late history merges cannot resurrect a run from a stale browser snapshot', () => {
  globalThis.localStorage = storage();
  const removed = {thread_id:'removed-run', status:'running'};
  const retained = {thread_id:'retained-run', status:'running'};
  rememberRun(1, removed);
  rememberRun(1, retained);
  const snapshot = getHistory(1);
  forgetRun(1, removed.thread_id);
  for (const rows of [[removed], [], null]) {
    assert.deepEqual(history.mergeHistoryList(snapshot, rows, 1).map(row => row.thread_id), ['retained-run']);
  }
  assert.equal(history.mergeHistoryList(snapshot, [removed], 2).length, 2);
  assert.deepEqual(getHistory(1).map(row => row.thread_id), ['retained-run']);
});
test('a cached-history write failure cannot turn a persisted hide into a reported failure', () => {
  globalThis.localStorage = storage();
  rememberRun(1, {thread_id:'partial-remove', query:'可恢复记录'});
  const setItem = localStorage.setItem.bind(localStorage);
  localStorage.setItem = (key, value) => {
    if (key === 'aiops:runs:v2:1') throw Error('quota');
    setItem(key, value);
  };
  assert.doesNotThrow(() => forgetRun(1, 'partial-remove'));
  assert.deepEqual(history.getHistory(1), []);
  assert.deepEqual(history.mergeHistoryList([], [
    {thread_id:'partial-remove', query:'可恢复记录', status:'completed'},
  ], 1), []);
});
test('unavailable persisted details cannot retain or display an old diagnosis', () => {
  const saved = {thread_id:'one', diagnosis:{kind:'confirmed_cause', cause_code:'old'}, query:'故障'};
  const refreshed = history.mergeHistoryRun(saved, {status:'pending_review', details_status:'unavailable'});
  assert.equal(refreshed.diagnosis, null);
  assert.equal(refreshed.details_status, 'unavailable');
  assert.equal(refreshed.status, 'pending_review');
  assert.equal(refreshed.query, '故障');
  const missing = history.mergeHistoryRun(saved, {status:'completed', details_status:'missing'});
  assert.equal(missing.diagnosis, null);
  assert.equal(missing.details_status, 'missing');
});
test('history reread preserves server time and explicit removal', () => {
  globalThis.localStorage = storage();
  rememberRun(1, {thread_id:'one', updated_at:'2026-11-10T00:00:00Z'});
  rememberRun(1, {thread_id:'one', status:'completed'});
  assert.equal(getHistory(1)[0].updated_at, '2026-11-10T00:00:00Z');
  forgetRun(1, 'one');
  assert.deepEqual(getHistory(1), []);
});
test('history refresh and reopening older runs keep the actual latest run first', () => {
  globalThis.localStorage = storage();
  for (const [thread_id, updated_at] of [['older', '2026-11-10T00:00:00Z'], ['latest', '2026-11-18T00:00:00Z']])
    rememberRun(1, {thread_id, updated_at});
  const before = getHistory(1);
  for (const row of before) rememberRun(1, {...row, status:'completed'});
  assert.deepEqual(getHistory(1).map(row => row.thread_id), ['latest', 'older']);
  rememberRun(1, {thread_id:'older', status:'completed'});
  assert.equal(getHistory(1)[0].thread_id, 'latest');
  rememberRun(1, {thread_id:'older', updated_at:'2026-11-18T01:00:00Z'});
  assert.equal(getHistory(1)[0].thread_id, 'older');
  localStorage.setItem('aiops:runs:v2:1', JSON.stringify([...before].reverse()));
  assert.equal(getHistory(1)[0].thread_id, 'latest');
});
test('malformed saved diagnosis input cannot break the new diagnosis form', () => {
  globalThis.sessionStorage = storage();
  for (const saved of [{query:{text:'bad'}}, {query:42}, ['wrong'], 'wrong']) {
    sessionStorage.setItem('aiops:draft:1', JSON.stringify(saved));
    assert.equal(readDraft(1), null);
  }
  sessionStorage.setItem('aiops:draft:1', JSON.stringify({query:'故障', terminalEnabled:'false'}));
  assert.deepEqual(readDraft(1), {query:'故障', terminalEnabled:false});
});
test('drafts are isolated and storage errors do not destroy the form', () => {
  globalThis.sessionStorage = storage();
  writeDraft(1, {query:'故障', terminalEnabled:true});
  assert.equal(readDraft(1).query, '故障');
  assert.equal(readDraft(2), null);
  assert.equal(readDraft(null), null);
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

test('same service on different hosts retains separate actions and target labels', () => {
  const rows = reportActions({recommendations:['host-a', 'host-b'].map(target_id =>
    ({action:'恢复应用', target_id, scope:{service:'app'}}))});
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map(row => row.target), ['host-a', 'host-b']);
});
test('workspace navigation is stored by user and run with validated tabs', () => {
  globalThis.sessionStorage = storage();
  history.writeWorkspace(1, 'run', {tab:'evidence', evidenceId:'e-one', cursorId:'e-two'});
  assert.equal(history.readWorkspace(1, 'run').evidenceId, 'e-one');
  assert.equal(history.readWorkspace(2, 'run'), null);
  assert.equal(history.readWorkspace(1, 'other'), null);
  sessionStorage.setItem('aiops:view:1:bad', '{"tab":"invalid"}');
  assert.equal(history.readWorkspace(1, 'bad'), null);
  sessionStorage.setItem('aiops:draft:null', '{"query":"must-not-read"}');
  assert.equal(readDraft(null), null);
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

test('live progress completes repeated plan entries without replacing earlier results', () => {
  let rows = advanceSteps([], {node:'planner', payload:{plan:['[并行] 日志', '日志']}});
  rows = advanceSteps(rows, {node:'executor', payload:{last_step:'日志', result_digest:'第一次'}});
  rows = advanceSteps(rows, {node:'executor', payload:{last_step:'日志', result_digest:'第二次'}});
  assert.deepEqual(rows.map(row => [row.done, row.result]), [[true, '第一次'], [true, '第二次']]);
});

test('replanning replaces obsolete pending steps while preserving completed history', () => {
  const rows = snapshotSteps([
    null,
    {node:'planner', payload:{plan:['日志', '旧计划']}},
    {node:'executor', payload:{last_step:'日志', result_digest:'完成'}},
    {node:'replanner', payload:{remaining_plan:['新计划']}},
    {node:'unknown', payload:{}},
  ]);
  assert.deepEqual(rows.map(row => row.text), ['日志', '新计划']);
  assert.equal(rows[0].result, '完成');
});

test('workspace navigation remains usable when session storage is denied', () => {
  globalThis.sessionStorage = { getItem() { throw Error('denied'); }, setItem() { throw Error('quota'); } };
  assert.equal(history.readWorkspace(1, 'run'), null);
  assert.doesNotThrow(() => history.writeWorkspace(1, 'run', {tab:'process'}));
});

test('review notes survive rereading and remain isolated by user and run', () => {
  globalThis.sessionStorage = storage();
  history.writeReviewDraft(1, 'run', '请补充下游证据');
  assert.equal(history.readReviewDraft(1, 'run'), '请补充下游证据');
  assert.equal(history.readReviewDraft(2, 'run'), '');
  assert.equal(history.readReviewDraft(1, 'other'), '');
  history.writeReviewDraft(1, 'run', '');
  assert.equal(history.readReviewDraft(1, 'run'), '');
  sessionStorage.setItem('aiops:review:1:run', JSON.stringify({note:'bad'}));
  assert.equal(history.readReviewDraft(1, 'run'), '');
  globalThis.sessionStorage = { getItem() { throw Error('denied'); }, setItem() { throw Error('quota'); } };
  assert.equal(history.readReviewDraft(1, 'run'), '');
  assert.doesNotThrow(() => history.writeReviewDraft(1, 'run', '保留'));
});

test('diagnosis stream dispatches only complete SSE frames', async () => {
  globalThis.localStorage = storage();
  const originalFetch = globalThis.fetch;
  const good = 'data: {"type":"status","thread_id":"saved-run"}';
  const terminal = 'data: {"type":"complete"}';
  const utf8 = new TextEncoder();
  try {
    for (const tail of [terminal, terminal + '\r\n', 'data: {"type":']) {
      globalThis.fetch = async () => new Response(new ReadableStream({start(controller) {
        for (const chunk of [good + '\r', '\n\r', '\n' + tail]) controller.enqueue(utf8.encode(chunk));
        controller.close();
      }}), {headers:{'Content-Type':'text/event-stream'}});
      const events = [];
      await stream('/aiops', {query:'read'}, {onEvent: row => events.push(row)});
      assert.deepEqual(events, [{type:'status', thread_id:'saved-run'}]);
    }
    globalThis.fetch = async () => new Response(good + '\n\n' + terminal + '\n\n', {
      headers:{'Content-Type':'text/event-stream'},
    });
    const events = [];
    await stream('/aiops', {query:'read'}, {onEvent: row => events.push(row)});
    assert.deepEqual(events.map(row => row.type), ['status', 'complete']);
  } finally { globalThis.fetch = originalFetch; }
});
