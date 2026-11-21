<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { request, stream } from "../lib/api";
import { getHistory, rememberRun, mergeHistoryRun, validRunId, readDraft, writeDraft, readReviewDraft, writeReviewDraft } from "../lib/history";
import { useLoad, confirmAction, dateTime, runStatus, tone } from "../lib/ui";
import { session } from "../lib/session";
import { snapshotSteps, advanceSteps, approvalUrl } from "../lib/diagnosis";
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
const toolCalls = ref([]), toolCallError = ref(""), snapshotError = ref(""), reviewInstruction = ref(""), reviewRevision = ref("");
let reviewDraftOwner = null;
function restoreReviewDraft(id) {
  reviewDraftOwner = null;
  reviewInstruction.value = readReviewDraft(session.user?.id, id);
  reviewDraftOwner = id ? { userId: session.user?.id, runId: id } : null;
}
function clearReviewDraft() {
  if (reviewDraftOwner) writeReviewDraft(reviewDraftOwner.userId, reviewDraftOwner.runId, "");
  reviewInstruction.value = "";
}
watch(reviewInstruction, value => {
  if (reviewDraftOwner && reviewDraftOwner.userId === session.user?.id)
    writeReviewDraft(reviewDraftOwner.userId, reviewDraftOwner.runId, value);
}, { flush: "sync" });
function clearAudit() { toolCalls.value = []; toolCallError.value = ""; snapshotError.value = ""; }
const hypotheses = ref([]),
  evidenceDetailError = ref(""),
  terminalUrl = ref("");
const readingPaused = ref(false);
const showingRun = computed(() => Boolean(threadId.value || restoreBusy.value || runStatusValue.value === 'running' || route.query.run != null));
const reviewAction = ref('');
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
let auditVersion = 0, evidenceVersion = 0, runReadVersion = 0, evidenceEventVersion = 0, stepEventVersion = 0, stoppedReading = false;
let startAttempt = 0;
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
    (threadId.value && runStatusValue.value === "disconnected") ||
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
  if (event.type === "usage") { usage.value = event; return; }
  runReadVersion++;
  if (event.knowledge_references) knowledgeReferences.value = event.knowledge_references;
  if (event.thread_id && validRunId(event.thread_id)) {
    threadId.value = event.thread_id;
    writeDraft(session.user?.id, null);
    router
      .replace({ path: "/aiops", query: { run: event.thread_id } })
      .catch(() => {});
    saveLocal(runStatusValue.value);
  }
  if (Object.hasOwn(event, "investigation")) investigation.value = event.investigation || null;
  if (Object.hasOwn(event, "diagnosis")) diagnosis.value = event.diagnosis || null;
  if (event.hypothesis_space) hypotheses.value = event.hypothesis_space;
  if (event.termcp_ui_url) terminalUrl.value = event.termcp_ui_url;
  switch (event.type) {
    case "plan":
      stepEventVersion++;
      steps.value = advanceSteps(steps.value, { node: "planner", payload: { plan: event.plan || [] } });
      statusText.value = event.message || "已制定排查计划";
      break;
    case "step_complete": {
      loadEvidence();
      stepEventVersion++;
      steps.value = advanceSteps(steps.value, { node: "executor", payload: {
        last_step: event.current_step || steps.value.find(step => !step.done)?.text,
        result_digest: event.message,
        completed_steps: event.completed_steps,
      } });
      statusText.value =
        event.message || `${doneCount.value}/${steps.value.length} 项完成`;
      break;
    }
    case "status":
      statusText.value = event.message || "正在分析";
      break;
    case "evidence":
      evidenceEventVersion++;
      if (!evidence.value.some(row => row.evidence_id === event.evidence_id)) evidence.value.push(event);
      statusText.value = event.message || "已获取新的现场证据";
      break;
    case "draft":
    case "report":
      if (Object.hasOwn(event, "report")) report.value = event.report || "";
      if (Object.hasOwn(event, "diagnosis")) diagnosis.value = event.diagnosis || null;
      statusText.value = event.message || "报告已更新";
      break;
    case "pending_terminal_approval":
      approval.value = event;
      runStatusValue.value = "pending_terminal";
      statusText.value = event.message || "等待命令审批";
      saveLocal("pending_terminal");
      break;
    case "pending_review":
      reviewRevision.value = event.expected_updated_at || "";
      if (!reviewDraftOwner || reviewDraftOwner.runId !== threadId.value) restoreReviewDraft(threadId.value);
      approval.value = event;
      if (Object.hasOwn(event, "draft")) report.value = event.draft || "";
      else if (Object.hasOwn(event, "response")) report.value = event.response || "";
      runStatusValue.value = "pending_review";
      statusText.value = event.message || "等待人工复核";
      saveLocal("pending_review");
      break;
    case "complete":
      if (Object.hasOwn(event, "diagnosis")) diagnosis.value = event.diagnosis || null;
      if (Object.hasOwn(event, "response")) report.value = event.response || "";
      runStatusValue.value = "completed";
      statusText.value = event.message || "诊断完成";
      approval.value = null;
      saveLocal("completed");
      refreshRunDetails();
      break;
    case "error":
      if (event.recoverable || event.stage === "resume_conflict") {
        runStatusValue.value = threadId.value ? "disconnected" : "failed";
        statusText.value = event.message || "连接异常，请重新读取诊断状态";
        warning.value = statusText.value;
        saveLocal(runStatusValue.value);
        break;
      }
      runStatusValue.value = "failed";
      if (Object.hasOwn(event, "diagnosis")) diagnosis.value = event.diagnosis || null;
      if (Object.hasOwn(event, "response")) report.value = event.response || "";
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
  const attempt = ++startAttempt;
  startBusy.value = true;
  let confirmed = true;
  try {
    if (terminalEnabled.value) confirmed = await confirmAction("启用受控终端", "终端命令需要单独审批，未审批不会执行。", "开始诊断", false, "aiops-confirm");
  } finally { if (attempt === startAttempt) startBusy.value = false; }
  if (!confirmed || version !== loadVersion.value || inputLocked.value) return;
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
  restoreReviewDraft("");
  reviewRevision.value = "";
  terminalUrl.value = "";
  selectedEvidence.value = null;
  loadVersion.value += 1;
  readingPaused.value = false;
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
    if (abortController.value !== controller) return;
    if (runStatusValue.value === "running") {
      runStatusValue.value = "disconnected";
      statusText.value = threadId.value ? "连接已结束，正在读取已保存的诊断" : "连接结束前未收到诊断编号，请先核对最近诊断再决定是否重试";
      saveLocal("disconnected");
    }
  } catch (e) {
    if (abortController.value !== controller) return;
    if (e.name === "AbortError") {
      runStatusValue.value = "disconnected";
      statusText.value = readingPaused.value ? "已暂停读取进度，服务端诊断仍可继续" : "诊断连接已中断";
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
  const liveVersion = evidenceEventVersion;
  const liveStepVersion = stepEventVersion;
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
      evidence.value = liveVersion === evidenceEventVersion ? list.evidence || []
        : [...new Map([...(list.evidence || []), ...evidence.value].map(row => [row.evidence_id, row])).values()];
    } else evidenceError.value = listResult.reason.message;
    if (snapshotResult.status === "fulfilled") {
      const snapshot = snapshotResult.value;
      const restoredSteps = snapshotSteps(snapshot.steps || []);
      if (liveStepVersion === stepEventVersion &&
          (restoredSteps.length || !["partial", "write_failed", "disabled"].includes(snapshot.status))) steps.value = restoredSteps;
      snapshotError.value = ({ partial: "部分步骤记录已损坏，回放不完整", write_failed: "部分步骤未能保存，回放不完整",
        disabled: "步骤快照未启用，无法从快照回放" })[snapshot.status] || "";
    } else snapshotError.value = snapshotResult.reason.message;
    if (callsResult.status === "fulfilled") toolCalls.value = callsResult.value.tool_calls || [];
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
  const valid = validRunId(id);
  startAttempt++; startBusy.value = false;
  resumeBusy.value = false;
  abortController.value?.abort();
  abortController.value = null;
  const version = ++loadVersion.value;
  stoppedReading = false;
  readingPaused.value = false;
  threadId.value = valid ? id : "";
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
  restoreReviewDraft(threadId.value);
  reviewRevision.value = "";
  diagnosis.value = null;
  investigation.value = null;
  knowledgeReferences.value = [];
  hypotheses.value = [];
  usage.value = null;
  selectedEvidence.value = null;
  rawEvidence.value = null;
  detail.value = null;
  evidenceDetailError.value = "";
  evidenceVersion++;
  if (!valid) {
    const draft = readDraft(session.user?.id);
    query.value = draft?.query || "";
    terminalEnabled.value = draft?.terminalEnabled === true;
    warning.value = "诊断编号格式无效，请从历史列表打开诊断或开始新诊断";
    statusText.value = "";
    runStatusValue.value = "unavailable";
    restoreBusy.value = false;
    return;
  }
  query.value = "";
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
    rememberRun(session.user?.id, mergeHistoryRun(local, {
      thread_id: id,
      status: run.status,
      ...run,
      query: query.value,
      updated_at: run.updated_at,
    }));
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
  reviewRevision.value = run.status === "pending_review" ? run.updated_at || "" : "";
  if (["running", "approved", "rejected", "completed", "failed", "pending_terminal"].includes(run.status)) clearReviewDraft();
  report.value = run.report || "";
  runStatusValue.value = run.status || "idle";
  statusText.value = runStatus(runStatusValue.value);
  diagnosis.value = run.diagnosis || null;
  investigation.value = run.investigation || null;
  knowledgeReferences.value = run.knowledge_references || [];
  hypotheses.value = run.hypothesis_space || [];
  approval.value = run.terminal_approval || null;
  terminalUrl.value = run.termcp_ui_url || "";
  warning.value = ({
    missing: "没有保存结构化诊断详情，仍可查看已保存的报告和证据。",
    unavailable: "结构化诊断详情暂不可用，可重新载入重试。",
  })[run.details_status] || "";
}
async function refreshRunDetails() {
  if (!threadId.value) return;
  const id = threadId.value;
  const version = loadVersion.value;
  const current = ++runReadVersion;
  try {
    const run = await request(
      `/aiops/runs/${encodeURIComponent(id)}`,
    );
    if (version !== loadVersion.value || id !== threadId.value || current !== runReadVersion) return;
    applyRun(run);
    evidenceError.value = "";
    await loadEvidence(id);
    if (version === loadVersion.value && id === threadId.value && current === runReadVersion) {
      saveLocal(runStatusValue.value, run.updated_at);
    }
  } catch (e) {
    if (version === loadVersion.value && id === threadId.value && current === runReadVersion) {
      evidenceError.value = e.message;
      if ([401, 403, 404].includes(e.status)) stoppedReading = true;
    }
  } finally {
    if (version === loadVersion.value && id === threadId.value && current === runReadVersion) scheduleRefresh();
  }
}
async function continueRun(action) {
  const reviewing = runStatusValue.value === "pending_review";
  if (!threadId.value || resumeBusy.value || (!reviewing && runStatusValue.value !== "pending_terminal")) return;
  if (reviewing && !["approve", "reject"].includes(action)) return;
  if (reviewing && !reviewRevision.value) { warning.value = "审核版本暂不可读取，请重新载入后复核"; return; }
  const pendingStatus = runStatusValue.value;
  reviewAction.value = action || "terminal";
  resumeBusy.value = true;
  runReadVersion++;
  stopRefresh(); stoppedReading = false;
  warning.value = "";
  const controller = new AbortController();
  abortController.value = controller;
  let receivedProgress = false;
  statusText.value = reviewing ? "正在提交复核" : "正在核对命令审批";
  try {
    await stream(
      `/aiops/runs/${encodeURIComponent(threadId.value)}/${reviewing ? 'review' : 'continue'}`,
      reviewing ? { action, expected_updated_at: reviewRevision.value, ...(reviewInstruction.value.trim() ? { instruction: reviewInstruction.value.trim() } : {}) } : undefined,
      { signal: controller.signal, onEvent: (event) => {
        if (abortController.value !== controller) return;
        if (!["error", "usage"].includes(event.type)) {
          if (!receivedProgress) runStatusValue.value = "running";
          receivedProgress = true;
          if (reviewing) clearReviewDraft();
        }
        onEvent(event);
      } },
    );
    if (abortController.value !== controller) return;
    if (runStatusValue.value === "running" || (!receivedProgress && runStatusValue.value === pendingStatus)) {
      runStatusValue.value = "disconnected";
      statusText.value = "请重新载入查看诊断状态";
    }
  } catch (e) {
    if (abortController.value !== controller) return;
    warning.value = e.message;
    runStatusValue.value = [403, 409, 422, 503].includes(e.status) ? pendingStatus : "disconnected";
    statusText.value = readingPaused.value ? "已暂停读取进度，服务端诊断仍可继续" : e.message;
    if (readingPaused.value) warning.value = "";
  } finally {
    if (abortController.value === controller) {
      resumeBusy.value = false;
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
function resetQuery(draft) {
  stopRefresh();
  knowledgeReferences.value = [];
  startAttempt++; startBusy.value = false;
  resumeBusy.value = false;
  loadVersion.value += 1;
  restoreBusy.value = false;
  abortController.value?.abort();
  abortController.value = null;
  query.value = draft?.query || "";
  terminalEnabled.value = draft?.terminalEnabled === true;
  readingPaused.value = false;
  hypotheses.value = [];
  investigation.value = null;
  approval.value = null;
  warning.value = "";
  terminalUrl.value = "";
  statusText.value = "";
  usage.value = null;
  selectedEvidence.value = null;
  evidenceError.value = "";
  report.value = "";
  diagnosis.value = null;
  evidence.value = [];
  steps.value = [];
  clearAudit();
  restoreReviewDraft("");
  reviewRevision.value = "";
  threadId.value = "";
  runStatusValue.value = "idle";
}
function stopReading() {
  stoppedReading = true;
  readingPaused.value = true;
  stopRefresh();
  abortController.value?.abort();
  runStatusValue.value = "disconnected";
  statusText.value = "已暂停读取进度，服务端诊断仍可继续";
}
watch([query, terminalEnabled], () => {
  if (!threadId.value && !restoreBusy.value) writeDraft(session.user?.id, { query: query.value, terminalEnabled: terminalEnabled.value });
});
watch([() => session.user?.id, () => session.user?.role], ([userId], [previousUserId]) => {
  selectedEvidence.value = null; rawEvidence.value = null; detail.value = null;
  clearAudit();
  if (threadId.value) restore(threadId.value);
  else if (userId !== previousUserId) {
    writeDraft(previousUserId, { query: query.value, terminalEnabled: terminalEnabled.value });
    const draft = readDraft(userId);
    resetQuery(draft);
  }
}, { flush: "sync" });
watch(
  [() => route.query.run, () => route.query.new],
  ([id, fresh]) => {
    if (fresh === "1") {
      if (threadId.value || runStatusValue.value !== "idle") resetQuery(readDraft(session.user?.id));
      else {
        const draft = readDraft(session.user?.id);
        query.value = typeof draft?.query === "string" ? draft.query : "";
        terminalEnabled.value = draft?.terminalEnabled === true;
      }
    } else if (id !== undefined) {
      if (id !== threadId.value) restore(id);
    } else {
      resetQuery(readDraft(session.user?.id));
    }
  },
  { immediate: true },
);
onUnmounted(() => { stopRefresh(); loadVersion.value += 1; abortController.value?.abort(); abortController.value = null; });
</script>

<template>
  <div class="page diagnosis-page">
    <PageHeader :title="showingRun ? '诊断详情' : '新建诊断'" :back="showingRun ? '/aiops/history' : undefined">
      <RouterLink v-if="showingRun" to="/aiops?new=1" class="button primary"><Icon name="plus" :size="16" />新建诊断</RouterLink>
      <RouterLink v-else to="/aiops/history" class="button"><Icon name="history" :size="16" />最近诊断</RouterLink>
    </PageHeader>
    <div v-if="!showingRun" class="diagnosis-compose">
      <form class="diagnosis-form" @submit.prevent="start">
        <label class="field" for="diagnosis-query">
          <span>故障现象</span>
          <textarea id="diagnosis-query" v-model="query" maxlength="12000"
            placeholder="例如：支付接口从 09:00 开始间歇返回 503" :disabled="inputLocked" required />
        </label>
        <div class="form-settings">
          <label class="check-label terminal-control"><input v-model="terminalEnabled" type="checkbox" :disabled="inputLocked" aria-describedby="terminal-scope" />启用受控终端</label>
          <p id="terminal-scope" class="muted">命令执行前需单独审批。</p>
        </div>
        <div v-if="warning" class="inline-feedback" role="alert">{{ warning }}</div>
        <p v-else-if="runStatusValue === 'disconnected'" role="status">{{ statusText }} <RouterLink to="/aiops/history">查看最近诊断</RouterLink></p>
        <button class="button primary" :disabled="inputLocked || !query.trim()">开始诊断<Icon name="arrow" :size="16" /></button>
      </form>
      <aside class="source-list" aria-labelledby="source-heading" :aria-busy="sourceLoading">
        <div class="section-heading">
          <h2 id="source-heading">证据来源状态</h2>
          <button class="button" :disabled="sourceLoading" @click="refreshSources()"><Icon name="refresh" :size="16" />{{ sourceLoading ? '正在刷新…' : '刷新状态' }}</button>
        </div>
        <p v-if="sourceError" role="alert">状态读取失败{{ dependenciesRows.length ? '，下方为上次状态' : '' }}：{{ sourceError }}</p>
        <Feedback v-else-if="sourceLoading && !dependenciesRows.length" :loading="true" />
        <p v-else-if="!dependenciesRows.length" class="muted">未返回证据来源状态</p>
        <div v-for="source in dependenciesRows" :key="source.key" class="service-line"><span>{{ source.label }}</span>
          <span :class="['status', tone(source.value)]">{{ source.value === 'ok' ? '可用' : source.value === 'disabled' ? '未启用' : '不可用' }}</span>
        </div>
      </aside>
    </div>
    <section v-else class="diagnosis-output" aria-label="本次诊断">
      <div class="run-strip">
        <span :class="['status', tone(runStatusValue)]" role="status">{{ runStatus(runStatusValue) }}</span>
        <div class="actions">
          <button v-if="runStatusValue === 'running' && !restoreBusy" class="button" @click="stopReading">暂停读取进度</button>
          <button v-else-if="threadId" :class="['button', { primary: ['disconnected', 'unavailable'].includes(runStatusValue) }]" :disabled="restoreBusy || resumeBusy" @click="restore(threadId)">
            <Icon name="refresh" :size="16" />{{ restoreBusy ? '正在读取…' : '重新载入' }}</button>
        </div>
      </div>
      <details v-if="query.trim() || threadId" class="run-context" :key="threadId">
        <summary>本次故障现象与编号</summary>
        <p v-if="query.trim()" class="run-description">{{ query }}</p>
        <p v-if="threadId" class="muted">诊断编号：<code>{{ threadId }}</code></p>
      </details>
      <p v-if="statusText && statusText !== runStatus(runStatusValue) && !warning" class="run-message muted">{{ statusText }}</p>
      <div v-if="warning" class="inline-feedback" role="alert">{{ warning }}</div>
      <section v-if="!restoreBusy && runStatusValue === 'pending_terminal'" class="decision-panel" aria-labelledby="terminal-heading" :aria-busy="resumeBusy">
        <h2 id="terminal-heading">终端命令待审批</h2>
        <pre v-if="approval?.command">{{ approval.command }}</pre>
        <div class="actions">
          <a v-if="safeTerminalUrl" class="button" :href="safeTerminalUrl" target="_blank" rel="noopener noreferrer">打开审批页（新窗口）</a>
          <button class="button primary" :disabled="resumeBusy" @click="continueRun()">{{ resumeBusy ? '正在核对审批…' : '检查审批并继续' }}</button>
        </div>
        <p v-if="!safeTerminalUrl" class="muted">未提供可用的命令审批页地址。</p>
      </section>
      <section v-if="!restoreBusy && runStatusValue === 'pending_review'" class="decision-panel" aria-labelledby="review-heading" :aria-busy="resumeBusy">
        <div class="section-heading"><h2 id="review-heading">报告待人工复核</h2>
          <button v-if="report || diagnosis" type="button" class="text-button" @click="$refs.workspace.showReport()">查看报告草稿</button>
        </div>
        <p v-if="!reviewRevision" role="status">审核版本暂不可读取，请重新载入后复核。</p>
        <label class="field">人工复核意见（选填）<textarea v-model="reviewInstruction" rows="2" maxlength="4000" :disabled="resumeBusy" /></label>
        <div class="actions">
          <button class="button primary" :disabled="resumeBusy || !reviewRevision" @click="continueRun('approve')">{{ resumeBusy && reviewAction === 'approve' ? '正在通过…' : '通过报告' }}</button>
          <button class="button" :disabled="resumeBusy || !reviewRevision" @click="continueRun('reject')">{{ resumeBusy && reviewAction === 'reject' ? '正在退回…' : '退回补查' }}</button>
        </div>
      </section>
      <div v-if="restoreBusy" class="feedback" role="status"><span class="spinner" />正在读取诊断</div>
      <DiagnosisWorkspace v-else-if="runStatusValue !== 'unavailable'" ref="workspace" :run-id="threadId" :report="report" :diagnosis="diagnosis"
        :investigation="investigation" :evidence="evidence" :hypotheses="hypotheses" :knowledge-references="knowledgeReferences"
        :plans="steps" :status="runStatusValue" :status-text="statusText" :usage="usage"
        :evidence-error="evidenceError" :snapshot-error="snapshotError" @evidence="viewEvidence" @retry-evidence="loadEvidence()">
        <template #audit><ToolCallLedger v-if="threadId" :calls="toolCalls" :error="toolCallError" @retry="loadEvidence()" /></template>
        <template #experience><ExperienceCandidate v-if="threadId" :thread-id="threadId" :status="runStatusValue" /></template>
      </DiagnosisWorkspace>
    </section>
    <Modal
      :model-value="Boolean(selectedEvidence)"
      :title="detailRecord ? `${detailRecord.label} · 证据来源` : '证据来源'"
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
        <button v-if="['admin', 'auditor'].includes(session.user?.role) && detail.raw != null" class="button" :aria-expanded="rawEvidence != null"
          aria-controls="evidence-raw" @click="rawEvidence != null ? rawEvidence = null : loadRaw()">
          {{ rawEvidence != null ? '收起现场原文' : '读取现场原文' }}
        </button>
        <Feedback
          v-if="detail.raw_status === 'unavailable'"
          error="留存原文暂不可读取。"
          @retry="viewEvidence(selectedEvidence)"
        />
        <p v-if="detail.raw_status === 'integrity_failed'" role="alert">留存原文未通过完整性或路径校验，不能展示为原始证据。</p>
        <pre v-if="rawEvidence != null" id="evidence-raw" class="source-raw" tabindex="0" aria-label="现场原文">{{ JSON.stringify(rawEvidence, null, 2) }}</pre>
      </template></Modal
    >
  </div>
</template>

<style scoped>
.diagnosis-compose { display: grid; grid-template-columns: minmax(0, 2fr) minmax(250px, 1fr); gap: 40px; max-width: 1120px; align-items: start; }
.diagnosis-form textarea { min-height: 176px; }
.form-settings { margin: 16px 0 24px; }
.form-settings p { margin: 4px 0 0 24px; }
.diagnosis-compose .source-list { margin: 0; border-left: 1px solid var(--line); padding-left: 24px; }
.section-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; }
.section-heading h2, .decision-panel h2 { margin: 0; font-size: 16px; }
.run-strip { justify-content: space-between; padding-bottom: 12px; }
.run-context { padding: 10px 0; border-top: 1px solid var(--line); overflow-wrap: anywhere; }
.run-context summary { cursor: pointer; width: fit-content; }
.run-context p { margin: 8px 0; }
.run-description { white-space: pre-wrap; max-width: 90ch; }
.run-message { margin: 4px 0 12px; overflow-wrap: anywhere; }
.decision-panel { margin: 12px 0; padding: 16px 0; border-block: 1px solid var(--line); }
.decision-panel pre, .source-raw { max-height: 45vh; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.decision-panel .actions { justify-content: flex-start; }
.decision-panel .field { max-width: 72ch; margin-top: 12px; }
.source-identifiers { margin: 20px 0; font-size: 13px; color: var(--muted); }
.source-identifiers summary { cursor: pointer; }
@media (max-width: 960px) {
  .diagnosis-compose { grid-template-columns: minmax(0, 1fr); gap: 24px; }
  .diagnosis-compose .source-list { border-left: 0; border-top: 1px solid var(--line); padding: 16px 0 0; }
}
</style>
