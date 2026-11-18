<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { request, stream } from "../lib/api";
import { getHistory, rememberRun, validRunId, readDraft, writeDraft } from "../lib/history";
import { useLoad, confirmAction, dateTime, runStatus, tone } from "../lib/ui";
import { session } from "../lib/session";
import { snapshotSteps, approvalUrl } from "../lib/diagnosis";
import { evidenceRows } from "../lib/diagnosisVisuals";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import DiagnosisWorkspace from "../components/DiagnosisWorkspace.vue";
import ToolCallLedger from "../components/ToolCallLedger.vue";
import ExperienceCandidate from "../components/ExperienceCandidate.vue";
import Modal from "../components/Modal.vue";
import Icon from "../components/Icon.vue";

const route = useRoute(),
  router = useRouter();
const query = ref(""),
  terminalEnabled = ref(false),
  warning = ref("");
const dependencies = ref({}),
  threadId = ref(""),
  report = ref(""),
  diagnosis = ref(null),
  investigation = ref(null),
  knowledgeReferences = ref([]),
  evidence = ref([]),
  steps = ref([]),
  runStatusValue = ref("idle"),
  statusText = ref(""),
  usage = ref(null),
  approval = ref(null),
  evidenceError = ref("");
const toolCalls = ref([]), toolCallError = ref(""), snapshotError = ref(""), reviewInstruction = ref("");
function clearAudit() { toolCalls.value = []; toolCallError.value = ""; snapshotError.value = ""; }
const hypotheses = ref([]),
  evidenceDetailError = ref(""),
  terminalUrl = ref("");
const compactInput = ref(true);
const detailRecord = computed(() => {
  if (!detail.value) return null;
  const row = evidenceRows(evidence.value, investigation.value).find(item => item.id === detail.value.evidence_id);
  const full = evidenceRows([detail.value], investigation.value)[0];
  return full ? { ...full, label: row?.label || full.label } : row;
});
const safeTerminalUrl = computed(() => approvalUrl(terminalUrl.value));
const selectedEvidence = ref(null),
  rawEvidence = ref(null),
  detail = ref(null),
  resumeBusy = ref(false),
  restoreBusy = ref(false);
const startBusy = ref(false);
const abortController = ref(null),
  loadVersion = ref(0),
  doneCount = computed(() => steps.value.filter((step) => step.done).length);
let refreshTimer;
let auditVersion = 0, evidenceVersion = 0, stoppedReading = false;
function stopRefresh() { clearTimeout(refreshTimer); }
function scheduleRefresh() {
  stopRefresh();
  if (["running", "approved", "rejected", "disconnected", "pending_review", "pending_terminal"].includes(runStatusValue.value) && !abortController.value && !stoppedReading)
    refreshTimer = setTimeout(refreshRunDetails, 1500);
}
const inputLocked = computed(
  () =>
    restoreBusy.value ||
    startBusy.value ||
    ["running", "approved", "rejected", "pending_review", "pending_terminal"].includes(
      runStatusValue.value,
    ),
);
const sourceNames = {
  probe: "主机采集",
  mcp_monitor: "指标服务",
  mcp_cls: "日志服务",
  knowledge: "知识检索",
};
const dependenciesRows = computed(() =>
  Object.entries(dependencies.value.services || {})
    .filter(([key]) => Object.hasOwn(sourceNames, key))
    .map(([key, value]) => ({
      key,
      label: sourceNames[key],
      value: value.status,
    })),
);
async function loadDependencies() {
  dependencies.value = await request("/health/dependencies");
}
const {
  loading: sourceLoading,
  error: sourceError,
  refresh: refreshSources,
} = useLoad(loadDependencies);
function saveLocal(status, updatedAt) {
  if (!threadId.value) return;
  const row = {
    thread_id: threadId.value,
    query: query.value || diagnosis.value?.conclusion || "",
    status,
    ...(updatedAt ? { updated_at: updatedAt } : {}),
    diagnosis: diagnosis.value || undefined,
  };
  rememberRun(session.user?.id, row);
}
function onEvent(event) {
  if (event.knowledge_references) knowledgeReferences.value = event.knowledge_references;
  if (event.thread_id && validRunId(event.thread_id)) {
    threadId.value = event.thread_id;
    router
      .replace({ path: "/aiops", query: { run: event.thread_id } })
      .catch(() => {});
    saveLocal(runStatusValue.value);
  }
  if (event.investigation) investigation.value = event.investigation;
  if (event.hypothesis_space) hypotheses.value = event.hypothesis_space;
  if (event.termcp_ui_url) terminalUrl.value = event.termcp_ui_url;
  switch (event.type) {
    case "plan":
      steps.value = (event.plan || []).map((text) => ({
        text: String(text).replace(/^\[并行\]\s*/, ""),
        done: false,
      }));
      statusText.value = event.message || "已制定排查计划";
      break;
    case "step_complete": {
      loadEvidence();
      const next = steps.value.find((step) =>
        event.current_step
          ? step.text === event.current_step.replace(/^\[并行\]\s*/, "")
          : !step.done,
      );
      if (next) {
        next.done = true;
        next.result = event.message;
      }
      statusText.value =
        event.message || `${doneCount.value}/${steps.value.length} 项完成`;
      break;
    }
    case "status":
      statusText.value = event.message || "正在分析";
      break;
    case "evidence":
      if (!evidence.value.some(row => row.evidence_id === event.evidence_id)) evidence.value.push(event);
      statusText.value = event.message || "已获取新的现场证据";
      break;
    case "draft":
    case "report":
      report.value = event.report || report.value;
      diagnosis.value = event.diagnosis || diagnosis.value;
      statusText.value = event.message || "报告已更新";
      break;
    case "usage":
      usage.value = event;
      break;
    case "pending_terminal_approval":
      approval.value = event;
      runStatusValue.value = "pending_terminal";
      statusText.value = event.message || "等待命令审批";
      saveLocal("pending_terminal");
      break;
    case "pending_review":
      approval.value = event;
      report.value = event.draft || event.response || report.value;
      runStatusValue.value = "pending_review";
      statusText.value = event.message || "等待人工复核";
      saveLocal("pending_review");
      break;
    case "complete":
      diagnosis.value = event.diagnosis || diagnosis.value;
      report.value = event.response || report.value;
      runStatusValue.value = "completed";
      statusText.value = event.message || "诊断完成";
      approval.value = null;
      saveLocal("completed");
      refreshRunDetails();
      break;
    case "error":
      runStatusValue.value = "failed";
      diagnosis.value = event.diagnosis || diagnosis.value;
      report.value = event.response || report.value;
      statusText.value = event.message || "诊断失败";
      warning.value = event.message || "诊断失败";
      saveLocal("failed");
      approval.value = null;
      break;
  }
}
async function start() {
  if (!query.value.trim() || inputLocked.value) return;
  const version = loadVersion.value;
  startBusy.value = true;
  let confirmed = true;
  try {
    if (terminalEnabled.value) confirmed = await confirmAction("启用受控终端", "本次诊断可能等待命令审批，继续吗？", "继续");
  } finally { startBusy.value = false; }
  if (!confirmed || version !== loadVersion.value || restoreBusy.value || ["running", "approved", "rejected", "pending_review", "pending_terminal"].includes(runStatusValue.value)) return;
  stopRefresh(); stoppedReading = false;
  abortController.value?.abort();
  abortController.value = new AbortController();
  const controller = abortController.value;
  threadId.value = "";
  report.value = "";
  diagnosis.value = null;
  investigation.value = null;
  knowledgeReferences.value = [];
  hypotheses.value = [];
  evidence.value = [];
  steps.value = [];
  clearAudit();
  usage.value = null;
  approval.value = null;
  warning.value = "";
  evidenceError.value = "";
  reviewInstruction.value = "";
  terminalUrl.value = "";
  selectedEvidence.value = null;
  writeDraft(session.user?.id, null);
  loadVersion.value += 1;
  compactInput.value = true;
  const sessionId = `web-${crypto.randomUUID()}`;
  runStatusValue.value = "running";
  statusText.value = "正在连接诊断服务";
  try {
    await stream(
      "/aiops",
      {
        query: query.value.trim(),
        session_id: sessionId,
        terminal_enabled: terminalEnabled.value,
      },
      { signal: controller.signal, onEvent: (event) => { if (abortController.value === controller) onEvent(event); } },
    );
    if (runStatusValue.value === "running") {
      runStatusValue.value = "disconnected";
      statusText.value = threadId.value ? "连接已结束，正在读取已保存的诊断" : "连接结束前未收到诊断编号，请先核对最近诊断再决定是否重试";
      saveLocal("disconnected");
    }
  } catch (e) {
    if (abortController.value !== controller) return;
    if (e.name === "AbortError") {
      runStatusValue.value = "disconnected";
      statusText.value = "诊断连接已中断";
    } else {
      runStatusValue.value = threadId.value ? "disconnected" : "failed";
      warning.value = e.message;
      statusText.value = e.message;
    }
    saveLocal(runStatusValue.value);
  } finally {
    if (abortController.value === controller) { abortController.value = null; scheduleRefresh(); }
  }
}
async function loadEvidence(id = threadId.value) {
  if (!validRunId(id)) return;
  const version = loadVersion.value;
  const current = ++auditVersion;
  evidenceError.value = "";
  try {
    const [listResult, snapshotResult, callsResult] = await Promise.allSettled([
      request(`/aiops/runs/${encodeURIComponent(id)}/evidence`),
      request(`/aiops/runs/${encodeURIComponent(id)}/steps`),
      request(`/aiops/runs/${encodeURIComponent(id)}/tool-calls`),
    ]);
    if (version !== loadVersion.value || id !== threadId.value || current !== auditVersion) return;
    if (listResult.status === "fulfilled") {
      const list = listResult.value;
      if (list.evidence?.length || !evidence.value.length) evidence.value = list.evidence || [];
    } else evidenceError.value = listResult.reason.message;
    if (snapshotResult.status === "fulfilled") {
      const snapshot = snapshotResult.value;
      const restoredSteps = snapshotSteps(snapshot.steps || []);
      if (restoredSteps.length || !steps.value.length) steps.value = restoredSteps;
      snapshotError.value = ({ partial: "部分步骤记录已损坏，回放不完整", write_failed: "部分步骤未能保存，回放不完整",
        disabled: "步骤快照未启用，无法从快照回放" })[snapshot.status] || "";
    } else snapshotError.value = snapshotResult.reason.message;
    toolCalls.value = callsResult.status === "fulfilled" ? callsResult.value.tool_calls || [] : [];
    toolCallError.value = callsResult.status === "rejected" ? callsResult.reason.message : "";
    return listResult.status === "fulfilled" ? listResult.value : null;
  } catch (e) {
    if (version !== loadVersion.value || id !== threadId.value || current !== auditVersion) return;
    evidenceError.value = e.message;
    return null;
  }
}
async function restore(id) {
  stopRefresh();
  if (!validRunId(id)) {
    warning.value = "诊断编号格式无效";
    return;
  }
  abortController.value?.abort();
  abortController.value = null;
  const version = ++loadVersion.value;
  stoppedReading = false;
  threadId.value = id;
  runStatusValue.value = "loading";
  statusText.value = "正在读取诊断";
  restoreBusy.value = true;
  warning.value = "";
  report.value = "";
  evidence.value = [];
  steps.value = [];
  clearAudit();
  approval.value = null;
  terminalUrl.value = "";
  evidenceError.value = "";
  reviewInstruction.value = "";
  query.value = "";
  diagnosis.value = null;
  investigation.value = null;
  knowledgeReferences.value = [];
  hypotheses.value = [];
  usage.value = null;
  selectedEvidence.value = null;
  try {
    const run = await request(`/aiops/runs/${encodeURIComponent(id)}`);
    if (version !== loadVersion.value) return;
    applyRun(run);
    await loadEvidence(id);
    if (version !== loadVersion.value) return;
    const local = getHistory(session.user?.id).find(
      (item) => item.thread_id === id,
    );
    query.value = run.query || local?.query || "";
    rememberRun(session.user?.id, {
      ...local,
      thread_id: id,
      status: run.status,
      query: query.value,
      updated_at: run.updated_at,
    });
  } catch (e) {
    if (version !== loadVersion.value) return;
    warning.value = e.message;
    runStatusValue.value = "unavailable";
    statusText.value = "诊断暂不可读取，可重新载入";
  } finally {
    if (version === loadVersion.value) {
      restoreBusy.value = false;
      scheduleRefresh();
    }
  }
}
function applyRun(run) {
  report.value = run.report || "";
  runStatusValue.value = run.status || "idle";
  statusText.value = runStatus(runStatusValue.value);
  diagnosis.value = run.diagnosis || null;
  investigation.value = run.investigation || null;
  knowledgeReferences.value = run.knowledge_references || [];
  hypotheses.value = run.hypothesis_space || [];
  approval.value = run.terminal_approval || null;
  terminalUrl.value = run.termcp_ui_url || "";
  warning.value = run.details_status === "unavailable" ? "运行记录已读取；结构化诊断详情暂不可用，可重新载入重试" : "";
}
async function refreshRunDetails() {
  if (!threadId.value) return;
  const id = threadId.value;
  const version = loadVersion.value;
  try {
    const run = await request(
      `/aiops/runs/${encodeURIComponent(id)}`,
    );
    if (version !== loadVersion.value || id !== threadId.value) return;
    applyRun(run);
    evidenceError.value = "";
    await loadEvidence(id);
    if (version === loadVersion.value && id === threadId.value) {
      saveLocal(runStatusValue.value, run.updated_at);
    }
  } catch (e) {
    if (version === loadVersion.value && id === threadId.value) {
      evidenceError.value = e.message;
      if ([401, 403, 404].includes(e.status)) stoppedReading = true;
    }
  } finally {
    if (version === loadVersion.value && id === threadId.value) scheduleRefresh();
  }
}
async function continueRun(action) {
  const reviewing = runStatusValue.value === "pending_review";
  if (!threadId.value || resumeBusy.value || (!reviewing && runStatusValue.value !== "pending_terminal")) return;
  if (reviewing && !["approve", "reject"].includes(action)) return;
  const pendingStatus = runStatusValue.value;
  resumeBusy.value = true;
  stopRefresh(); stoppedReading = false;
  warning.value = "";
  const controller = new AbortController();
  abortController.value = controller;
  runStatusValue.value = "running";
  statusText.value = "正在核对审批状态";
  try {
    await stream(
      `/aiops/runs/${encodeURIComponent(threadId.value)}/${reviewing ? 'review' : 'continue'}`,
      reviewing ? { action, ...(reviewInstruction.value.trim() ? { instruction: reviewInstruction.value.trim() } : {}) } : undefined,
      { signal: controller.signal, onEvent: (event) => { if (abortController.value === controller) onEvent(event); } },
    );
    if (runStatusValue.value === "running") {
      runStatusValue.value = "disconnected";
      statusText.value = "请重新载入查看诊断状态";
    }
  } catch (e) {
    if (abortController.value !== controller) return;
    warning.value = e.message;
    runStatusValue.value = [403, 409, 422, 503].includes(e.status) ? pendingStatus : "disconnected";
    statusText.value = e.message;
  } finally {
    resumeBusy.value = false;
    if (abortController.value === controller) {
      saveLocal(runStatusValue.value);
      abortController.value = null;
      scheduleRefresh();
    }
  }
}
async function viewEvidence(id) {
  const current = ++evidenceVersion;
  const runId = threadId.value;
  const role = session.user?.role;
  selectedEvidence.value = id;
  rawEvidence.value = null;
  detail.value = null;
  evidenceDetailError.value = "";
  try {
    const result = await request(
      `/aiops/runs/${encodeURIComponent(threadId.value)}/evidence/${encodeURIComponent(id)}`,
    );
    if (current === evidenceVersion && selectedEvidence.value === id && threadId.value === runId && session.user?.role === role) {
      const { raw_ref, ...safe } = result;
      detail.value = safe;
    }
  } catch (e) {
    if (current === evidenceVersion && selectedEvidence.value === id && threadId.value === runId) evidenceDetailError.value = e.message;
  }
}
function loadRaw() {
  if (
    ["admin", "auditor"].includes(session.user?.role) &&
    detail.value?.raw != null
  )
    rawEvidence.value = detail.value.raw;
}
function resetQuery() {
  writeDraft(session.user?.id, null);
  stopRefresh();
  knowledgeReferences.value = [];
  loadVersion.value += 1;
  restoreBusy.value = false;
  abortController.value?.abort();
  abortController.value = null;
  query.value = "";
  terminalEnabled.value = false;
  hypotheses.value = [];
  investigation.value = null;
  approval.value = null;
  warning.value = "";
  terminalUrl.value = "";
  statusText.value = "";
  usage.value = null;
  selectedEvidence.value = null;
  evidenceError.value = "";
  router.replace({ path: "/aiops", query: { new: "1" } });
  report.value = "";
  diagnosis.value = null;
  evidence.value = [];
  steps.value = [];
  clearAudit();
  reviewInstruction.value = "";
  threadId.value = "";
  runStatusValue.value = "idle";
}
function stopReading() {
  stoppedReading = true; stopRefresh();
  abortController.value?.abort();
  if (!abortController.value) { runStatusValue.value = "disconnected"; statusText.value = "已停止读取进度，服务端诊断仍可继续；重新载入可查看结果"; }
}
watch([query, terminalEnabled], () => {
  if (!threadId.value && !restoreBusy.value) writeDraft(session.user?.id, { query: query.value, terminalEnabled: terminalEnabled.value });
});
watch([() => session.user?.id, () => session.user?.role], () => {
  selectedEvidence.value = null; rawEvidence.value = null; detail.value = null;
  clearAudit();
  if (threadId.value) restore(threadId.value);
});
watch(
  [() => route.query.run, () => route.query.new],
  ([id, fresh]) => {
    if (fresh === "1") {
      if (threadId.value || runStatusValue.value !== "idle") resetQuery();
      else {
        const draft = readDraft(session.user?.id);
        query.value = typeof draft?.query === "string" ? draft.query : "";
        terminalEnabled.value = draft?.terminalEnabled === true;
      }
    } else if (typeof id === "string") {
      if (id !== threadId.value) restore(id);
    } else {
      const draft = readDraft(session.user?.id);
      const previous = getHistory(session.user?.id)[0];
      if (draft?.query) { query.value = draft.query; terminalEnabled.value = draft.terminalEnabled === true; }
      else if (previous)
        router.replace({ path: "/aiops", query: { run: previous.thread_id } });
    }
  },
  { immediate: true },
);
onUnmounted(() => { stopRefresh(); loadVersion.value += 1; abortController.value?.abort(); });
</script>

<template>
  <div class="page diagnosis-page">
    <PageHeader title="故障诊断"
      ><button
        v-if="!threadId"
        class="button"
        :disabled="sourceLoading"
        @click="refreshSources()"
      >
        <Icon name="refresh" :size="16" />刷新状态
      </button></PageHeader
    >
    <div :class="['diagnosis-layout', { 'has-run': threadId || runStatusValue === 'running' }]">
      <section v-if="(!threadId && runStatusValue !== 'running') || !compactInput" class="diagnosis-input">
        <form @submit.prevent="start">
          <label class="field" for="diagnosis-query"
            ><span>故障现象</span
            ><textarea
              id="diagnosis-query"
              v-model="query"
              maxlength="12000"
              placeholder="描述告警、错误信息和发生时间"
              :disabled="inputLocked"
              required
            /></label
          ><label class="check-label terminal-control"
            ><input
              v-model="terminalEnabled"
              type="checkbox"
              :disabled="inputLocked"
            />启用受控终端</label
          ><button
            class="button primary"
            :disabled="inputLocked || !query.trim()"
          >
            <span v-if="runStatusValue === 'running'" class="spinner" />{{
              runStatusValue === "running" ? "诊断中…" : "开始诊断"
            }}<Icon
              v-if="runStatusValue !== 'running'"
              name="arrow"
              :size="16"
            /></button
          ><button
            v-if="runStatusValue === 'disconnected'"
            type="button"
            class="text-button"
            @click="restore(threadId)"
          >
            恢复诊断
          </button>
        </form>
        <div class="source-list">
          <h3>证据来源</h3>
          <Feedback
            v-if="sourceLoading && !dependenciesRows.length"
            :loading="true"
          />
          <div
            v-for="source in dependenciesRows"
            :key="source.key"
            class="service-line"
          >
            <span>{{ source.label }}</span
            ><span :class="['status', tone(source.value)]">{{
              source.value === "ok"
                ? "可用"
                : source.value === "disabled"
                  ? "未启用"
                  : "不可用"
            }}</span>
          </div>
          <button
            v-if="sourceError"
            class="text-button"
            @click="refreshSources()"
          >
            {{ sourceError }} · 重试</button
          ><span v-if="!dependenciesRows.length && !sourceLoading" class="muted"
            >无法读取服务状态</span
          >
        </div>
      </section>
      <section class="diagnosis-output">
        <div v-if="threadId || runStatusValue === 'running'" class="run-strip">
          <span :class="['status', tone(runStatusValue)]">{{
            statusText || runStatus(runStatusValue)
          }}</span
          ><button v-if="query.trim()" class="text-button" :aria-expanded="!compactInput" @click="compactInput = !compactInput">故障描述</button
          ><button
            class="text-button"
            :disabled="restoreBusy || !threadId"
            @click="restore(threadId)"
          >
            重新载入</button
          ><button v-if="runStatusValue === 'running'" class="text-button danger" @click="stopReading">停止读取</button><button class="text-button" @click="resetQuery">新建诊断</button>
        </div>
        <div v-if="warning" class="inline-feedback" role="alert">
          {{ warning }}
        </div>
        <div
          v-if="runStatusValue === 'pending_terminal'"
          class="inline-feedback info"
        >
          <div class="grow">
            <strong>终端命令待审批</strong>
            <pre v-if="approval?.command">{{ approval.command }}</pre>
          </div>
          <a
            v-if="safeTerminalUrl"
            class="button"
            :href="safeTerminalUrl"
            target="_blank"
            rel="noopener noreferrer"
            >打开审批页</a
          ><button
            class="button primary"
            :disabled="resumeBusy"
            @click="continueRun"
          >
            {{ resumeBusy ? "核对中…" : "检查审批并继续" }}
          </button>
        </div>
        <div v-if="restoreBusy" class="feedback">
          <span class="spinner" />正在读取诊断
        </div>
        <template v-else>
          <Feedback v-if="evidenceError" :error="evidenceError" @retry="loadEvidence()" />
          <p v-if="snapshotError" role="alert">{{ snapshotError }}</p>
          <DiagnosisWorkspace :run-id="threadId" :report="report" :diagnosis="diagnosis"
            :investigation="investigation" :evidence="evidence" :hypotheses="hypotheses"
            :knowledge-references="knowledgeReferences"
            :plans="steps" :status="runStatusValue" :status-text="statusText" :usage="usage"
            @evidence="viewEvidence" />
          <ToolCallLedger v-if="threadId" :calls="toolCalls" :error="toolCallError" @retry="loadEvidence()" />
          <ExperienceCandidate v-if="threadId" :thread-id="threadId" :status="runStatusValue" />
          <div v-if="runStatusValue === 'pending_review'" class="inline-feedback">
            <label class="field">人工复核意见<textarea v-model="reviewInstruction" maxlength="4000" :disabled="resumeBusy" /></label>
            <button class="button primary" :disabled="resumeBusy" @click="continueRun('approve')">通过报告</button>
            <button class="button" :disabled="resumeBusy" @click="continueRun('reject')">退回补查</button>
          </div>
        </template>
      </section>
    </div>
    <Modal
      :model-value="Boolean(selectedEvidence)"
      title="证据来源"
      wide
      @update:model-value="!$event && (selectedEvidence = null, rawEvidence = null, detail = null, evidenceVersion++)"
      ><Feedback
        v-if="evidenceDetailError"
        :error="evidenceDetailError"
        @retry="viewEvidence(selectedEvidence)"
      /><Feedback v-else-if="!detail" :loading="true" /><template v-else
        ><dl class="detail-facts">
          <dt>观测对象</dt>
          <dd>{{ detailRecord?.label }} · {{ detailRecord?.title || "现场观测" }}</dd>
          <dt>采集时间</dt>
          <dd>{{ dateTime(detail.collected_at) }}</dd>
          <dt>观测</dt>
          <dd>{{ detailRecord?.result || "—" }}</dd>
        </dl>
        <details class="source-identifiers"><summary>追溯信息</summary><dl class="detail-facts"><dt>证据编号</dt><dd>{{ detail.evidence_id }}</dd><dt>目标编号</dt><dd>{{ detail.target_id || "—" }}</dd><template v-if="detail.raw_hash"><dt>内容指纹</dt><dd>{{ detail.raw_hash }}</dd></template></dl></details>
        <button
          v-if="
            ['admin', 'auditor'].includes(session.user?.role) &&
            detail.raw != null
          "
          class="button"
          :disabled="rawEvidence"
          @click="loadRaw"
        >
          {{ rawEvidence ? "已读取原文" : "读取现场原文" }}
        </button>
        <p v-if="detail.raw_status === 'unavailable'" role="alert">留存原文暂不可读取，请重试或联系管理员核查留存目录。</p>
        <p v-if="detail.raw_status === 'integrity_failed'" role="alert">留存原文未通过完整性或路径校验，不能展示为原始证据。</p>
        <pre v-if="rawEvidence">{{ JSON.stringify(rawEvidence, null, 2) }}</pre>
      </template></Modal
    ><button v-if="restoreBusy" class="sr-only" aria-live="polite">
      正在恢复诊断
    </button>
  </div>
</template>

<style scoped>
.source-identifiers { margin: 20px 0; font-size: 13px; color: var(--muted, #605e5c); }
.source-identifiers summary { cursor: pointer; }
.diagnosis-layout.has-run { display: flex; flex-direction: column; gap: 24px; }
.has-run .diagnosis-input { border-right: 0; border-bottom: 1px solid var(--line); padding: 0 0 24px; display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 40px; }
.has-run .diagnosis-input textarea { min-height: 96px; }
.has-run .source-list { margin-top: 0; }
.has-run .diagnosis-output { width: 100%; }
.has-run .run-strip { padding-bottom: 4px; }
@media(max-width:760px) { .has-run .diagnosis-input { grid-template-columns: minmax(0, 1fr); gap: 20px; } }
</style>
