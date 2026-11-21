// Direct execution of the data projections; no Vue transforms.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { evidenceRows, topology, reportOverview } from '../frontend/src/lib/diagnosisVisuals.js';

const record = (id, target, kind, payload) => ({ evidence_id: id, target_id: target, kind, summary: JSON.stringify(payload) });
const log = (id, target, service, port, upstream, extra = []) => record(id, target, 'text_logs', {
  service, lines: [{ event: 'service_started', listen_port: port, ...(upstream ? { upstream: { host: '127.0.0.1', port: upstream } } : {}) }, ...extra].map(JSON.stringify),
});
const rows = evidenceRows([
  log('app-a', 'a', 'app', 4001, 4002), log('db-a', 'a', 'db', 4002),
  log('app-b', 'b', 'app', 5001, 4002), log('db-b', 'b', 'db', 4002),
  record('port-a', 'a', 'ports', { local_port: 4002, matched_count: 0 }),
]);
const nodeFor = (graph, service, target) => graph.nodes.find(node => node.service === service && node.target === target);

test('same service and port on different targets keep separate evidence and edges', () => {
  const graph = topology(rows);
  assert.deepEqual(nodeFor(graph, 'db', 'a').evidence.map(row => row.id), ['db-a', 'port-a']);
  assert.deepEqual(nodeFor(graph, 'db', 'b').evidence.map(row => row.id), ['db-b']);
  assert.equal(graph.edges.length, 2);
  for (const edge of graph.edges) {
    const from = graph.nodes.find(node => node.id === edge.from), to = graph.nodes.find(node => node.id === edge.to);
    assert.equal(from.target, to.target);
  }
});
test('node identity stays stable as another target arrives and records reorder', () => {
  const before = topology(rows.filter(row => row.target === 'a'));
  const after = topology([...rows].reverse());
  assert.equal(nodeFor(before, 'app', 'a').id, nodeFor(after, 'app', 'a').id);
  assert.equal(nodeFor(before, 'db', 'a').id, nodeFor(after, 'db', 'a').id);
});
test('unknown targets and ambiguous ports never borrow another service identity', () => {
  const graph = topology([...rows,
    ...evidenceRows([record('unknown', '', 'ports', { local_port: 4002, matched_count: 0 })]),
  ]);
  const unknown = graph.nodes.find(node => node.evidence.some(row => row.id === 'unknown'));
  assert.equal(unknown.target, '');
  assert.deepEqual(unknown.evidence.map(row => row.id), ['unknown']);
  const ambiguous = topology(evidenceRows([
    log('one', 'a', 'db', 4002), log('two', 'a', 'cache', 4002),
    record('ambiguous', 'a', 'ports', { local_port: 4002 }),
  ]));
  assert.equal(ambiguous.nodes.find(node => node.evidence.some(row => row.id === 'ambiguous')).service, '主机');
});
test('registration dependencies bind only to their target', () => {
  const inventory = target => record('inventory-' + target, target, 'inventory', {
    configured_services: { app: {}, db: {} }, dependency_details: { query: { source_service: 'app' } },
  });
  const graph = topology(evidenceRows([inventory('a'), inventory('b')]), { target_id: 'a', dependency_services: { query: 'db' } });
  assert.equal(graph.edges.length, 1);
  assert.equal(graph.nodes.find(node => node.id === graph.edges[0].from).target, 'a');
});
test('confirmed report keeps a cited same-target chain when same names exist elsewhere', () => {
  const chain = evidenceRows([
    log('down', 'a', 'downstream', 4002, null, [{ event: 'shutdown_requested' }, { event: 'service_exited' }]),
    log('app', 'a', 'app', 4001, 4002, [{ status: 503, request_id: 'request', upstream_request: { connection_established: false } }]),
    log('entry', 'b', 'edge', 4000, 4001, [{ status: 503, request_id: 'request', upstream_request: { response_status: 503 } }]),
    log('other-app', 'b', 'app', 4001, 4002), log('other-down', 'b', 'downstream', 4002),
  ]);
  const diagnosis = { kind: 'confirmed_cause', root_cause_code: 'downstream_stopped_after_request', evidence: chain.map(row => ({ evidence_id: row.id })) };
  assert.deepEqual(reportOverview(diagnosis, chain).steps.map(step => step.id), ['down', 'app']);
});
