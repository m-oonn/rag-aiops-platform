const operationNames = {
  inventory: "现场登记", services: "服务状态", processes: "进程快照", ports: "监听端口",
  text_logs: "应用日志", configuration: "配置快照", dependency_probe: "连接探测",
  metrics: "指标", events: "系统事件",
};
const unique = (values) => [...new Set(values.filter(Boolean))];
// Presentation vocabulary only. Original evidence and candidate text remain available.
const vocabulary = {
  mall_portal: "商城买家业务服务", mall_admin: "商城后台业务服务", mall_search: "商城搜索服务",
  mall_mysql: "商城数据库", mall_redis: "商城缓存与会话", mall_rabbitmq: "订单消息队列",
  mall_mongo: "商品浏览记录库", mall_elasticsearch: "商品搜索引擎",
  mall_home: "商城首页内容", mall_product: "商品详情", mall_search_api: "独立搜索接口",
  mall_buyer: "买家页面", mall_buyer_api: "买家页面的业务接口", mall_admin_entry: "管理后台页面",
  mall_portal_mysql: "买家服务到数据库", mall_portal_redis: "买家服务到缓存",
  mall_portal_rabbitmq: "买家服务到消息队列", mall_portal_mongo: "买家服务到浏览记录库",
  mall_portal_elasticsearch: "买家服务到搜索引擎", mall_search_engine: "搜索服务到搜索引擎",
  edge: "访问入口", localapp: "业务应用", downstream: "下游服务",
  ecom_web: "商城网站", ecom_postgres: "商品数据库", ecom_redis: "缓存与会话", ecom_worker: "后台任务处理",
  ecom_entry: "商城首页", ecom_cart: "购物车", ecom_static: "页面样式资源", ecom_database: "数据库查询", ecom_cache: "购物车缓存", ecom_tasks: "后台任务通道", ecom_worker_database: "后台进程的数据库查询",
  postgres: "数据库", redis: "缓存", worker: "后台任务进程",
  probe_dependency_probe: "依赖连接检查", probe_config_snapshot: "公开配置检查",
  ToolException: "取证未完成", URLError: "网址访问失败", OperationalError: "数据库操作失败",
  running: "正在运行", healthy: "健康检查通过", stopped: "已停止", exited: "已退出",
  exit_code: "退出状态", oom_killed: "因内存不足退出", OOM: "内存不足",
  SIGKILL: "强制终止信号", false: "否", true: "是", loopback: "本机回环地址",
  no_worker_reply: "未收到任务处理进程回应", authentication_rejected: "数据库拒绝身份验证",
  controlled_stop: "受控停止", shutdown_completed: "停止完成",
  shutdown_requested: "收到停止请求", service_exited: "服务退出", service_started: "服务启动",
  request_completed: "请求完成", TimeoutError: "请求超时", ConnectionRefusedError: "连接被拒绝",
  ConnectionResetError: "连接被重置", receive_headers: "等待响应头", connect: "建立连接",
  downstream_port: "下游端口", upstream_timeout_seconds: "下游请求超时（秒）",
  source_sha256: "配置指纹", file_presence: "停止标记文件", LISTEN: "监听",
  POSTGRES_HOST: "数据库地址", POSTGRES_PORT: "数据库端口", ALLOWED_HOSTS: "允许访问的主机",
  static_url: "静态资源网址前缀", static_directories: "静态资源查找目录", static_files: "资源查找结果",
  static_mounts: "静态目录挂载", destination: "容器目录", registered_source: "登记源目录",
  actual_source: "实际源目录", registered_resources_present: "登记源中的资源存在性", found: "已找到",
  downstream_stopped_after_request: "收到停止请求后退出",
};
export function readableText(value = "") {
  return String(value).replace(/\b[A-Za-z_][A-Za-z_0-9]*\b/g, token => vocabulary[token] || token);
}
export function fieldLabel(key) { return vocabulary[key] || key; }
export function serviceLabel(name) {
  return vocabulary[name] || name || "服务";
}
function candidateTitle(text) {
  const clean = readableText(text)
    .replace(/实例\s+[a-f0-9]{24,64}/gi, "")
    .replace(/[（(]PID\s*\d+[）)]/gi, "")
    .replace(/在\s*\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*启动并监听\s*\d+\s*后/g, "启动后")
    .replace(/收到\s*受控停止\s*停止请求/g, "收到受控停止请求")
    .replace(/\s+/g, " ").trim();
  const first = clean.split(/[，；。\n（]/)[0].trim();
  return first.length > 64 ? `${first.slice(0, 64)}…` : first;
}
export function parsePayload(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) return value;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch { return null; }
}
export function clockTime(value) {
  if (value == null || value === "") return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("zh-CN", { hour12: false });
}
export function conditionText(condition, fallback = "") {
  if (!condition) return fallback;
  const object = serviceLabel((condition.object_name || "对象").split("#")[0]);
  const expected = condition.expected;
  if (condition.field === "state") return `${object}${({running: "正在运行", stopped: "已停止", paused: "已暂停", stop_pending: "正在停止", start_pending: "正在启动"})[expected] || "的运行状态待核对"}`;
  if (condition.field === "query") return `${object}${({ok: "实际功能检查通过", failed: "实际功能检查失败", no_worker_reply: "未收到后台任务进程回应"})[expected] || "功能状态待核对"}`;
  if (condition.field === "http.status") return `${object}返回 HTTP ${expected}`;
  if (condition.field === "error_category") return `${object}${readableText(expected)}`;
  if (condition.field === "process_present" && typeof expected === "boolean")
    return `${object} ${expected ? "存在匹配进程" : "未发现匹配进程"}`;
  if (condition.field === "listening" && typeof expected === "boolean")
    return `端口 ${object} ${expected ? "正在监听" : "未监听"}`;
  if (condition.field === "tcp") return `${object}${expected === "failed" ? " TCP 连接失败" : expected === "ok" ? "连接可达" : ` TCP ${expected}`}`;
  if (condition.field === "upstream_request.connection_established" && typeof expected === "boolean")
    return `${object}${expected ? "已连接到依赖服务" : "未能连接到依赖服务"}`;
  if (condition.field === "upstream_request.phase") return `${object}请求停在${readableText(expected)}阶段`;
  if (condition.field === "upstream_request.response_status" || condition.field === "status")
    return `${object}收到${expected >= 400 ? "失败" : "接口"}响应`;
  if (/^(processes|ports|text_logs)\//.test(fallback)) return `${object}的现场状态待核对`;
  return fallback;
}
export function questionText(question) {
  const text = typeof question === "string" ? question : question?.question || "";
  const match = text.match(/^(dependency_probe|services|ports|processes)\/([^:]+):\s*([\w.]+)\s*==\s*(.+)$/);
  if (match) {
    try {
      return `尚未确认：${conditionText({ operation: match[1], object_name: match[2], field: match[3], expected: JSON.parse(match[4]) }, readableText(text))}`;
    } catch { /* Preserve unrecognized original text. */ }
  }
  return readableText(text);
}
export function logEvents(payload) {
  return (Array.isArray(payload?.lines) ? payload.lines : []).map((line, index) => {
    const data = parsePayload(line);
    const labels = { service_started: "服务启动", shutdown_requested: "收到停止请求", service_exited: "服务退出", request_completed: "请求完成" };
    return { index, data, time: data?.at || data?.timestamp || "",
      label: labels[data?.event] || "日志记录",
      text: data ? [data.status != null && `HTTP ${data.status}`, readableText(data.message || data.msg || ""), readableText(data.reason || ""),
        data.listen_port != null && `监听端口 ${data.listen_port}`,
        data.upstream_request?.phase && `阶段：${readableText(data.upstream_request.phase)}`,
        data.upstream_request?.connection_established === false && "连接未建立",
        readableText(data.error_type || "")].filter(Boolean).join(" · ") : readableText(line) };
  });
}
function observationText(kind, payload, fallback) {
  if (!payload) return fallback || "摘要不完整，查看来源";
  if (payload.error) return typeof payload.error === "string" ? payload.error : "采集未完成";
  if (kind === "inventory") return payload.configured_services ? `${Object.keys(payload.configured_services).length} 项服务登记` : "已返回现场登记";
  if (kind === "services") return ({running: "服务正在运行", stopped: "服务已停止", paused: "服务已暂停"})[payload.state] || "已返回服务状态";
  if (kind === "processes") return payload.matched_count != null
    ? (payload.matched_count === 0 ? "未发现匹配进程" : `匹配 ${payload.matched_count} 个进程`)
    : "已返回进程快照";
  if (kind === "ports" && Array.isArray(payload.ports)) return payload.ports.some(row => row.status === "LISTEN")
    ? `发现 ${payload.ports.filter(row => row.status === "LISTEN").length} 项监听`
    : "返回范围内未发现监听（连接残留不算监听）";
  if (kind === "ports") return payload.matched_count != null
    ? (payload.matched_count === 0 ? "返回范围内无监听" : `匹配 ${payload.matched_count} 项端口`)
    : "已返回端口快照";
  if (kind === "dependency_probe") return [payload.tcp && `TCP ${payload.tcp === "ok" ? "可达" : payload.tcp === "failed" ? "失败" : payload.tcp}`,
    payload.probe_kind !== "tcp" && payload.query && ({ok: "实际功能检查通过", failed: "实际功能检查失败", no_worker_reply: "未收到后台任务进程回应"})[payload.query],
    payload.error_category === "authentication_rejected" && "数据库拒绝身份验证",
    payload.http?.status != null && `HTTP ${payload.http.status}`, payload.http?.error,
    payload.elapsed_ms != null && `${payload.elapsed_ms} ms`].filter(Boolean).join(" · ") || "已返回连接探测";
  if (kind === "configuration" && payload.source === "container_start_environment")
    return "已读取容器启动时的公开配置；尚不能证明运行时已加载，展开可核对";
  if (kind === "configuration" && payload.source === "mounted_spring_config_snapshot")
    return "已读取挂载配置文件及启动参数；尚不能证明应用已加载，展开可核对";
  if (kind === "configuration" && payload.static_mounts?.length)
    return "已核对运行配置、静态资源查找与目录挂载，展开可核对";
  if (kind === "configuration") return Object.values(payload.values || {}).some(value => value && typeof value === "object")
    ? "已读取运行中的公开配置，展开可核对连接地址与访问规则"
    : Object.entries(payload.values || {}).map(([key, value]) => `${fieldLabel(key)}：${value}`).join(" · ") || "已返回配置快照";
  if (kind === "text_logs") {
    const events = logEvents(payload);
    return events.length ? events.map((item) => item.label).join(" → ") : "返回日志为空";
  }
  return fallback || "已取得现场记录";
}
export function evidenceRows(items = [], investigation = {}) {
  const summaries = investigation?.evidence_summaries || [];
  const rows = new Map();
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const id = item.evidence_id || item.id;
    if (!id) continue;
    const extra = summaries.find((row) => row.evidence_id === id) || {};
    const payload = parsePayload(item.summary) || parsePayload(item.payload);
    const kind = item.kind || extra.operation || item.operation || item.source || "";
    const subject = payload?.service || payload?.dependency || extra.subject?.service || extra.subject?.dependency || "";
    const port = payload?.local_port ?? extra.subject?.local_port;
    const fallback = typeof item.summary === "string" && !item.summary.trim().startsWith("{") ? item.summary : extra.summary;
    const unavailable = ["unavailable", "not_applicable"].includes(extra.status) || Boolean(payload?.error);
    const partial = extra.status === "partial" || (!payload && typeof item.summary === "string" && item.summary.trim().startsWith("{"));
    const abnormal = (kind === "processes" && payload?.matched_count === 0) ||
      (kind === "services" && ["stopped", "paused", "stop_pending"].includes(payload?.state)) ||
      (kind === "ports" && port != null && payload?.matched_count === 0) ||
      (kind === "dependency_probe" && (payload?.tcp === "failed" || payload?.http?.status >= 400 || payload?.http?.error || ["failed", "no_worker_reply"].includes(payload?.query))) ||
      logEvents(payload).some((event) => event.data?.status >= 400);
    rows.set(id, { id, kind, payload, subject, port, time: item.collected_at || extra.collected_at || "",
      title: [subject ? serviceLabel(subject) : (port != null ? `端口 ${port}` : ""), operationNames[kind] || "现场记录"].filter(Boolean).join(" · "),
      result: observationText(kind, payload, fallback),
      state: unavailable ? "unavailable" : partial ? "partial" : abnormal ? "abnormal" : "observed",
      stateLabel: unavailable ? "未取得" : partial ? "部分结果" : abnormal ? "发现异常" : "已采集",
      target: item.target_id || "", source: item.source || "", hash: item.raw_hash || "",
      rawAvailable: Boolean(item.raw_available), fresh: item.fresh,
    });
  }
  return [...rows.values()].sort((a, b) => {
    const left = Date.parse(a.time), right = Date.parse(b.time);
    return Number.isFinite(left) && Number.isFinite(right) ? left - right : 0;
  }).map((row, index) => ({ ...row, number: index + 1, label: `E${String(index + 1).padStart(2, "0")}` }));
}
export function topology(rows = [], registration = {}) {
  const services = new Set();
  const ports = new Map();
  const mapping = registration.dependency_services || {};
  for (const row of rows) {
    Object.keys(row.payload?.configured_services || {}).filter((name) =>
      !registration.allowed_services || registration.allowed_services.includes(name)).forEach((name) => services.add(name));
    if (row.subject) services.add(mapping[row.subject] || row.subject);
    if (row.subject && row.payload?.port != null) ports.set(row.subject, row.payload.port);
    for (const event of logEvents(row.payload)) {
      if (row.subject && event.data?.listen_port != null) ports.set(row.subject, event.data.listen_port);
    }
  }
  const owner = (row) => mapping[row.subject] || row.subject || (row.port != null
    ? [...ports].find(([, port]) => String(port) === String(row.port))?.[0] : "");
  const nodes = [...services].map((name) => ({ id: name, port: ports.get(name),
    evidence: rows.filter((row) => owner(row) === name),
  }));
  if (rows.some((row) => !owner(row))) nodes.push({ id: "主机", evidence: rows.filter((row) => !owner(row)) });
  const edges = [];
  for (const row of rows) for (const [dependency, detail] of Object.entries(row.payload?.dependency_details || {})) {
    const from = detail?.source_service, to = mapping[dependency];
    if (from && to && from !== to && services.has(from) && services.has(to) &&
        !edges.some(edge => edge.from === from && edge.to === to))
      edges.push({ from, to, evidence: row.id, label: "登记依赖 · 因果需另行核验" });
  }
  for (const row of rows) for (const event of logEvents(row.payload)) {
    const upstream = event.data?.upstream;
    if (upstream?.port == null || !row.subject) continue;
    // Match a port only within this target; equal ports on other hosts are not a service mapping.
    const matches = nodes.filter((node) => String(node.port) === String(upstream.port) && node.evidence.some((item) => item.target === row.target));
    const target = matches.length === 1 ? matches[0].id : "";
    const localHost = ["127.0.0.1", "localhost", "::1"].includes(upstream.host);
    if (target && localHost && target !== row.subject && !edges.some((edge) => edge.from === row.subject && edge.to === target))
      edges.push({ from: row.subject, to: target, evidence: row.id, label: "日志配置指向 · 因果未确认" });
  }
  return { nodes, edges };
}
export function visualCandidates(investigation = {}, diagnosis = {}, hypotheses = []) {
  const candidates = investigation?.candidates || investigation?.hypotheses || hypotheses;
  const alternatives = diagnosis?.alternatives || [];
  const source = candidates.length ? candidates : alternatives;
  return source.map((item, index) => {
    const id = item.id || item.hypothesis_id || String(index);
    const alternative = alternatives.find((row) => row.hypothesis_id === id) || {};
    const checks = investigation?.candidate_check_progress?.[id] || [];
    const condition = item.condition || alternative.condition;
    const confirmed = diagnosis?.kind === "confirmed_cause" && diagnosis.hypothesis_id === id;
    // Lifecycle "dropped" means no longer pursued, not disproved. Only use explicit verdicts.
    const status = confirmed ? "confirmed" : item.status === "dropped" ? "dropped"
      : ["supported", "excluded"].includes(alternative.status) ? alternative.status : item.status || item.state || "unresolved";
    // A cited alternative can remain unresolved even when its prose argues against it.
    const relation = ["support", "contradict"].includes(item.relation) ? item.relation : "neutral";
    const citations = confirmed ? (diagnosis.evidence || []).map(row => row.evidence_id) : [];
    const evidence = unique([...citations, ...(item.evidence_ids || []), ...(alternative.evidence || []).map((row) => row.evidence_id), ...checks.flatMap((check) => check.evidence_ids || [])]);
    const original = item.explanation || item.hypothesis || item.name || item.cause || "";
    return { id, number: `H${index + 1}`, text: confirmed ? reportOverview(diagnosis).causeTitle : conditionText(condition, candidateTitle(original)), original,
      status, statusLabel: { confirmed: "已确认原因", supported: "有证据支持", excluded: "已排除", dropped: "已停止排查" }[status] || "待验证",
      type: confirmed ? "原因解释" : condition ? "现场条件" : "原因解释", relation, evidence,
      relations: evidence.map((evidenceId) => ({ id: evidenceId,
        relation: citations.includes(evidenceId) ? "citation" : (item.evidence_ids || []).includes(evidenceId) ? relation : "neutral" })),
      limitation: readableText(alternative.limitation || item.limitation || ""),
      question: readableText(item.check?.discriminating_question || alternative.check?.discriminating_question || checks[0]?.question || ""),
      nextCheck: readableText(item.check?.next_check || alternative.check?.next_check || checks[0]?.next_check || ""),
    };
  }).filter((row) => row.text);
}
export function reportOverview(diagnosis = {}, rows = []) {
  const kind = diagnosis?.kind;
  const code = kind === "confirmed_cause" ? diagnosis.root_cause_code : "";
  const titles = {
    downstream_stopped_after_request: ["下游服务停止，业务请求失败", "下游服务收到停止请求后退出"],
    configured_downstream_endpoint_mismatch: ["应用连接到了错误的下游地址", "应用连接地址与登记地址不一致"],
    configuration_value_rejected: ["应用无法使用当前配置", "配置值被应用拒绝"],
    registered_service_stopped: [`${serviceLabel(diagnosis?.cause_subject || "服务")}已停止，对应访问不可用`, "当前服务停止导致对应访问不可用"],
    registered_host_rejected: ["商城拒绝了当前网址的访问，已确认是主机访问配置限制", "应用配置不允许当前网址的主机名"],
    registered_dependency_endpoint_mismatch: ["应用连接地址配置有误，登记地址可达而实际连接失败", "应用加载的连接地址与可用登记地址不一致"],
    registered_authentication_rejected: ["应用连接数据库的身份验证被拒绝", "数据库可用，但本应用使用的身份验证未通过"],
    registered_static_mount_mismatch: ["页面样式资源缺失，已确认静态目录挂载与登记不符", "静态目录挂载不符，应用找不到登记资源"],
  };
  const facts = reportFacts(diagnosis, rows);
  const title = titles[code]?.[0] || (kind === "localized_fault"
    ? `${facts[0] ? serviceLabel(facts[0].object) : "已检查的服务"}出现异常，原因还未确认`
    : kind === "healthy_within_scope" ? "本次检查未发现故障"
    : kind === "confirmed_cause" ? "已确认本次故障原因" : kind === "unlocated" ? "暂时还没找到故障位置" : "诊断结果");
  const causeTitle = titles[code]?.[1] || candidateTitle(diagnosis?.conclusion || "已确认本次故障原因");
  const cited = new Set((diagnosis?.evidence || []).map(item => item.evidence_id));
  const logs = rows.filter(row => cited.has(row.id) && row.kind === "text_logs");
  const steps = [];
  if (code === "registered_service_stopped") {
    const stopped = rows.find(row => cited.has(row.id) && row.subject === diagnosis.cause_subject
      && row.kind === "services" && row.payload?.state === "stopped");
    const mapping = diagnosis.asset_registration?.dependency_services || {};
    const failedPaths = stopped ? rows.filter(row => cited.has(row.id) && row.target === stopped.target
      && row.kind === "dependency_probe" && mapping[row.subject] === stopped.subject
      && row.payload?.tcp === "failed") : [];
    const failed = failedPaths.find(row => row.payload?.probe_kind !== "tcp" && row.payload?.query === "failed") || failedPaths[0];
    if (stopped && failed) {
      steps.push({ id: stopped.id, object: serviceLabel(stopped.subject), title: "服务已停止", icon: "logout", tone: "cause" });
      steps.push({ id: failed.id, object: serviceLabel(failed.subject),
        title: failed.payload.probe_kind !== "tcp" && failed.payload.query === "failed" ? "实际功能检查失败" : "对应连接失败", icon: "close", tone: "affected" });
    }
  }
  // Present an already confirmed chain only from its cited, linked request records.
  if (code === "downstream_stopped_after_request") {
    const stopped = logs.find(row => {
      const events = logEvents(row.payload).map(event => event.data);
      return events.some(event => event?.event === "shutdown_requested") && events.some(event => event?.event === "service_exited");
    });
    if (stopped) {
      steps.push({ id: stopped.id, object: serviceLabel(stopped.subject), title: "收到停止请求后退出", icon: "logout", tone: "cause" });
      const graph = topology(rows);
      const app = logs.find(row => row.target === stopped.target && graph.edges.some(edge => edge.from === row.subject && edge.to === stopped.subject)
        && logEvents(row.payload).some(event => event.data?.status >= 400 && event.data?.upstream_request?.connection_established === false));
      if (app) {
        const request = logEvents(app.payload).find(event => event.data?.status >= 400 && event.data?.upstream_request?.connection_established === false)?.data;
        steps.push({ id: app.id, object: serviceLabel(app.subject), title: "无法连接下游服务", icon: "close", tone: "affected" });
        const entry = request?.request_id && logs.find(row => row.target === app.target && graph.edges.some(edge => edge.from === row.subject && edge.to === app.subject)
          && logEvents(row.payload).some(event => event.data?.request_id === request.request_id && event.data?.upstream_request?.response_status >= 400));
        if (entry) steps.push({ id: entry.id, object: serviceLabel(entry.subject), title: "用户请求失败", icon: "close", tone: "affected" });
      }
    }
  }
  return { title, causeTitle, steps };
}
export function reportFacts(diagnosis = {}, rows = []) {
  const findings = diagnosis?.observed_findings || [];
  const seen = new Set();
  return findings.flatMap((finding) => {
    const id = finding.evidence_id;
    const evidence = rows.find((row) => row.id === id);
    if (seen.has(id)) return [];
    seen.add(id);
    const scope = finding.scope || {};
    return [{ id, object: scope.service || scope.dependency || (scope.local_port != null ? `端口 ${scope.local_port}` : "现场"),
      text: evidence?.result || finding.summary, label: evidence?.label || "证据", state: evidence?.state || "observed" }];
  });
}
export function reportActions(diagnosis = {}) {
  const actions = [];
  for (const item of diagnosis?.recommendations || []) {
    if (!item) continue;
    const action = typeof item === "string" ? item : item.action || item.recommendation;
    if (!action) continue;
    const scope = item.scope || {};
    const sameScope = row => {
      const keys = unique([...Object.keys(row.scope), ...Object.keys(scope)]);
      return keys.every(key => row.scope[key] === scope[key]);
    };
    const previous = actions.find((row) => row.action === action && sameScope(row));
    if (previous) {
      previous.evidence = unique([...previous.evidence, ...(item.evidence || []).map((row) => row.evidence_id)]);
      previous.preconditions = unique([...previous.preconditions, ...(item.preconditions || [])]);
      previous.risks = unique([...previous.risks, ...(item.risks || [])]);
      previous.verification = unique([...previous.verification, ...(item.verification_steps || [])]);
    }
    else actions.push({ action, evidence: (item.evidence || []).map((row) => row.evidence_id),
      scope: item.scope || {}, preconditions: item.preconditions || [], risks: item.risks || [], verification: item.verification_steps || [] });
  }
  return actions;
}
