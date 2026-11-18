import { describe, expect, it } from "vitest";
import { evidenceRows, logEvents, readableText, visualCandidates, topology, reportFacts, reportActions, reportOverview } from "./diagnosisVisuals";
const record = (id, kind, payload, second = 1, target = "host-a") => ({ evidence_id: id, kind, summary: JSON.stringify(payload), collected_at: `2026-11-14T01:00:${String(second).padStart(2, '0')}Z`, target_id: target });

describe("diagnosis visual projections", () => {
  it("keeps a partial inventory usable when dependency details contain null", () => {
    const rows = evidenceRows([record("inventory", "inventory", {
      configured_services: { web: {}, db: {} },
      dependency_details: { missing: null, query: { source_service: "web" } },
    })]);
    const graph = topology(rows, { dependency_services: { missing: "db", query: "db" } });
    expect(graph.edges).toEqual([{ from: "web", to: "db", evidence: "inventory", label: "登记依赖 · 因果需另行核验" }]);
    expect(graph.nodes.map(node => node.id)).toContain("web");
  });
  it("limits host inventory nodes to the resolved business registration", () => {
    const rows = evidenceRows([record("inventory", "inventory", { configured_services: { old_web: {}, new_web: {}, new_db: {} } })]);
    const graph = topology(rows, { allowed_services: ["new_web", "new_db"] });
    expect(graph.nodes.map(node => node.id)).toEqual(["new_web", "new_db", "主机"]);
  });
  it("does not promote a TCP failure to a function test and prefers a real query in a confirmed chain", () => {
    const rows = evidenceRows([
      record("state", "services", { service: "db", state: "stopped" }),
      record("tcp", "dependency_probe", { dependency: "socket", probe_kind: "tcp", tcp: "failed", query: "failed" }),
      record("query", "dependency_probe", { dependency: "actual", probe_kind: "django_database", tcp: "failed", query: "failed" }),
    ]);
    expect(rows.find(row => row.id === "tcp").result).not.toContain("功能检查");
    const overview = reportOverview({ kind: "confirmed_cause", root_cause_code: "registered_service_stopped",
      cause_subject: "db", evidence: rows.map(row => ({evidence_id: row.id})),
      asset_registration: { dependency_services: {socket: "db", actual: "db"} } }, rows);
    expect(overview.steps[1].id).toBe("query");
  });
  it("distinguishes stopped-container startup configuration from loaded settings", () => {
    const [row] = evidenceRows([record("config", "configuration", {
      source: "container_start_environment", values: { POSTGRES_PORT: "5433" },
    })]);
    expect(row.result).toContain("尚不能证明运行时已加载");
    expect(row.result).not.toContain("运行中的");
  });
  it("does not present a mounted Spring file as runtime effective configuration", () => {
    const [row] = evidenceRows([record("spring-config", "configuration", {
      source: "mounted_spring_config_snapshot", runtime_effective_values_confirmed: false,
      values: { "spring.datasource.url": { host: "mysql", port: 3307 } },
    })]);
    expect(row.result).toContain("尚不能证明应用已加载");
    expect(row.result).not.toContain("运行中的");
  });
  it("shows registered shop dependencies and actual stopped/query states without inventing a cause", () => {
    const rows = evidenceRows([
      record("inventory", "inventory", { configured_services: { web: {}, db: {} }, dependency_details: { query: { source_service: "web" } } }),
      record("db-state", "services", { service: "db", state: "stopped" }),
      record("query-state", "dependency_probe", { dependency: "query", tcp: "ok", query: "failed" }),
    ]);
    expect(rows.filter(row => row.state === "abnormal")).toHaveLength(2);
    const graph = topology(rows, { dependency_services: { query: "db" } });
    expect(graph.edges).toEqual([{from: "web", to: "db", evidence: "inventory", label: "登记依赖 · 因果需另行核验"}]);
    expect(graph.nodes.find(node => node.id === "db").evidence).toHaveLength(2);
  });
  it("orders and deduplicates actual observations without treating stale data as a collection failure", () => {
    const rows = evidenceRows([
      record("port", "ports", { local_port: 4634, matched_count: 0 }, 5),
      { ...record("process", "processes", { service: "downstream", matched_count: 0 }), fresh: false },
      record("process", "processes", { service: "downstream", matched_count: 0 }),
    ]);
    expect(rows.map(row => row.id)).toEqual(["process", "port"]);
    expect(rows[0]).toMatchObject({ label: "E01", state: "abnormal", stateLabel: "发现异常", result: "未发现匹配进程" });
    expect(evidenceRows([{ ...record("old", "processes", { service: "edge", matched_count: 2 }), fresh: false }])[0].state).toBe("observed");
  });
  it("keeps truncated JSON and missing counts unknown instead of inventing zero matches", () => {
    const rows = evidenceRows([
      { evidence_id: "truncated", kind: "ports", summary: '{"ports":[{"pid":12' },
      record("missing", "processes", { service: "edge", processes: [] }),
    ]);
    expect(rows[0].payload).toBeNull();
    expect(rows[0].stateLabel).toBe("部分结果");
    expect(rows[0].result).toBe("摘要不完整，查看来源");
    expect(rows[1]).toMatchObject({ state: "observed", result: "已返回进程快照" });
    expect(evidenceRows([record("unknown", "inventory", {})])[0].result).not.toContain("0");
  });
  it("keeps causal status and relation independent from citations and counterargument prose", () => {
    const rows = visualCandidates({ candidates: [{ id: "h1", explanation: "配置错误", status: "active", relation: "neutral", evidence_ids: [] }, { id: "h2", explanation: "连接失败", status: "excluded", relation: "contradict", evidence_ids: ["ev2"] }],
      candidate_check_progress: { h1: [{ evidence_ids: ["ev1"], question: "是否错配" }] } }, { alternatives: [{ hypothesis_id: "h1", status: "unresolved", noncritical_reason: "端点错配不成立", evidence: [{ evidence_id: "ev1" }], limitation: "已见相同配置" }] });
    expect(rows[0]).toMatchObject({ statusLabel: "待验证", relation: "neutral", question: "是否错配", evidence: ["ev1"], relations: [{ id: "ev1", relation: "neutral" }] });
    expect(rows[1]).toMatchObject({ statusLabel: "已排除", relations: [{ id: "ev2", relation: "contradict" }] });
  });
  it("maps only observed local upstream endpoints and exposes the mapping evidence", () => {
    const rows = evidenceRows([
      record("catalog", "inventory", { configured_services: { edge: {}, app: {}, downstream: {} } }),
      record("app-log", "text_logs", { service: "app", lines: [JSON.stringify({ event: "service_started", listen_port: 4633, upstream: { host: "127.0.0.1", port: 4634 } })] }),
      record("down-log", "text_logs", { service: "downstream", lines: [JSON.stringify({ event: "service_started", listen_port: 4634 })] }),
      record("port", "ports", { local_port: 4634, matched_count: 0 }),
    ]);
    const graph = topology(rows);
    expect(graph.edges).toEqual([{ from: "app", to: "downstream", evidence: "app-log", label: "日志配置指向 · 因果未确认" }]);
    expect(graph.nodes.find(node => node.id === "downstream").evidence.map(row => row.id)).toEqual(["down-log", "port"]);
    expect(graph.nodes.find(node => node.id === "edge").evidence).toEqual([]);
    rows.find(row => row.id === "app-log").target = "other-host";
    expect(topology(rows).edges).toEqual([]);
  });
  it("deduplicates findings by evidence and actions by text while retaining all references", () => {
    const data = { observed_findings: [{ evidence_id: "ev1", scope: { local_port: 4634 }, summary: "端口未监听" }, { evidence_id: "ev1", scope: { local_port: 4634 }, summary: "期望端口未监听" }], recommendations: [{ action: "复测", evidence: [{ evidence_id: "ev1" }] }, { action: "复测", evidence: [{ evidence_id: "ev2" }] }] };
    expect(reportFacts(data)).toEqual([{ id: "ev1", object: "端口 4634", text: "端口未监听", label: "证据", state: "observed" }]);
    expect(reportActions(data)).toHaveLength(1);
    expect(reportActions(data)[0].evidence).toEqual(["ev1", "ev2"]);
  });
});

describe("readable diagnosis without changing the source", () => {
  it("shows a short confirmed cause and traces the same cited request without exposing internal fields", () => {
    const event = (data) => JSON.stringify({ event: "request_completed", ...data });
    const rows = evidenceRows([
      record("down", "text_logs", { service: "downstream", lines: [event({ event: "service_started", listen_port: 4634 }), event({ event: "shutdown_requested" }), event({ event: "service_exited" })] }),
      record("app", "text_logs", { service: "localapp", lines: [event({ event: "service_started", listen_port: 4633, upstream: { host: "127.0.0.1", port: 4634 } }), event({ request_id: "one-request", status: 503, upstream_request: { connection_established: false } })] }),
      record("entry", "text_logs", { service: "edge", lines: [event({ upstream: { host: "127.0.0.1", port: 4633 }, request_id: "one-request", status: 503, upstream_request: { response_status: 503 } })] }),
    ]);
    const diagnosis = { kind: "confirmed_cause", root_cause_code: "downstream_stopped_after_request", conclusion: "controlled_stop connection_established=false", evidence: rows.map(row => ({ evidence_id: row.id })) };
    expect(reportOverview(diagnosis, rows)).toMatchObject({ title: "下游服务停止，业务请求失败", steps: [{ id: "down", object: "下游服务" }, { id: "app", object: "业务应用" }, { id: "entry", object: "访问入口" }] });
    expect(reportOverview({ ...diagnosis, kind: "localized_fault" }, rows).steps).toEqual([]);
    expect(reportOverview(null).title).toBe("诊断结果");
    expect(reportOverview({ kind: "unlocated" }).title).toBe("暂时还没找到故障位置");
    expect(reportOverview({ ...diagnosis, evidence: [{ evidence_id: "down" }] }, rows).steps.map(row => row.id)).toEqual(["down"]);
    const mismatched = rows.map(row => row.id === "entry" ? { ...row, payload: { ...row.payload, lines: row.payload.lines.map(line => line.replace("one-request", "other-request")) } } : row);
    expect(reportOverview(diagnosis, mismatched).steps.map(row => row.id)).toEqual(["down", "app"]);
    expect(reportOverview(diagnosis, rows.map(row => row.id === "app" ? { ...row, target: "other-host" } : row)).steps).toHaveLength(1);
  });
  it("keeps lifecycle, verified conditions and the confirmed cause distinct", () => {
    const candidates = [{ id: "root", explanation: "raw instance", status: "active" }, { id: "observation", status: "active", condition: { object_name: "localapp#secret-request", field: "upstream_request.connection_established", expected: false } }, { id: "old", explanation: "旧猜测", status: "dropped" }, { id: "unknown", explanation: "另一个原因", status: "active" }];
    const rows = visualCandidates({ candidates }, { kind: "confirmed_cause", root_cause_code: "downstream_stopped_after_request", hypothesis_id: "root", alternatives: [{ hypothesis_id: "observation", status: "supported", verification: "predicate_verified" }] });
    expect(rows.map(row => row.statusLabel)).toEqual(["已确认原因", "有证据支持", "已停止排查", "待验证"]);
    expect(rows[0].text).toBe("下游服务收到停止请求后退出");
    expect(rows[1].text).toBe("业务应用未能连接到依赖服务");
    expect(candidates[0].explanation).toBe("raw instance");
    expect(rows[2].status).not.toBe("excluded");
    const [confirmed] = visualCandidates({ candidates: [candidates[0]] }, { kind: "confirmed_cause", hypothesis_id: "root", evidence: [{ evidence_id: "final-reference" }] });
    expect(confirmed.relations).toEqual([{ id: "final-reference", relation: "citation" }]);
    const [unconfirmed] = visualCandidates({ candidates: [candidates[0]] }, { kind: "localized_fault", hypothesis_id: "root", evidence: [{ evidence_id: "finding-only" }] });
    expect(unconfirmed.relations).toEqual([]);
  });
  it("keeps long instance identifiers and causal claims in expandable originals", () => {
    const original = "worker 实例 5bd350547f6d4968b03a36c3acb46b31（PID 27136）在 01:03:53 启动并监听 4634 后收到 controlled_stop 停止请求并完成退出，导致业务失败";
    const [candidate] = visualCandidates({ candidates: [{ id: "h1", explanation: original, status: "active" }] });
    expect(candidate.text).toBe("后台任务进程 启动后收到受控停止请求并完成退出");
    expect(candidate.original).toBe(original);
    expect(candidate.statusLabel).toBe("待验证");
    expect(candidate.text).not.toContain("导致业务失败");
  });
  it("translates known log and configuration terms while retaining unknown data", () => {
    const data = { event: "request_completed", status: 503, error_type: "TimeoutError", upstream_request: { phase: "connect", connection_established: false } };
    const [event] = logEvents({ lines: [JSON.stringify(data)] });
    expect(event.text).toBe("HTTP 503 · 阶段：建立连接 · 连接未建立 · 请求超时");
    expect(event.data).toEqual(data);
    const [config] = evidenceRows([record("config", "configuration", { values: { downstream_port: 4634, upstream_timeout_seconds: 0.5, custom_key: 7 } })]);
    expect(config.result).toBe("下游端口：4634 · 下游请求超时（秒）：0.5 · custom_key：7");
    expect(readableText("NotControlledStop controlled_stop_extra")).toBe("NotControlledStop controlled_stop_extra");
  });
  it("keeps negation and uncertainty in shortened candidate headings", () => {
    const [candidate] = visualCandidates({ candidates: [{ explanation: "worker 可能从未启动或启动失败（而非停止后退出）", status: "excluded" }] });
    expect(candidate.text).toBe("后台任务进程 可能从未启动或启动失败");
    expect(candidate.statusLabel).toBe("已排除");
  });
});

it("distinguishes leftover connections from a listening socket", () => {
  const [row] = evidenceRows([record("port", "ports", { local_port: 8310, matched_count: 2,
    ports: [{ status: "TIME_WAIT" }, { status: "TIME_WAIT" }] })]);
  expect(row.result).toBe("返回范围内未发现监听（连接残留不算监听）");
});

it("explains a verified static mount failure and successful connections in Chinese", () => {
  expect(reportOverview({kind: "confirmed_cause", root_cause_code: "registered_static_mount_mismatch"}).title)
    .toBe("页面样式资源缺失，已确认静态目录挂载与登记不符");
  expect(visualCandidates({candidates: [{condition: {object_name: "ecom_redis", field: "tcp", expected: "ok"}}]})[0].text)
    .toBe("缓存与会话连接可达");
});
