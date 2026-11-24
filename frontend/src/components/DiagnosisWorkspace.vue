<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import { clockTime, endpointComparison, evidenceRows, fieldLabel, logEvents, readableText, reportActions, reportFacts, reportOverview, reportQuestions, serviceLabel, topology, visualCandidates } from "../lib/diagnosisVisuals";
import DiagnosisTopology from "./DiagnosisTopology.vue";
import DiagnosisCharts from "./DiagnosisCharts.vue";
import KnowledgeReferences from "./KnowledgeReferences.vue";
import Markdown from "./Markdown.vue";
import Icon from "./Icon.vue";
import { readWorkspace, writeWorkspace } from "../lib/history";
import { session } from "../lib/session";
const props = defineProps({
  runId: String, report: String, diagnosis: Object, investigation: Object,
  evidence: { type: Array, default: () => [] }, hypotheses: { type: Array, default: () => [] },
  plans: { type: Array, default: () => [] }, status: String, statusText: String, usage: Object,
  knowledgeReferences: { type: Array, default: () => [] }, evidenceError: String, snapshotError: String,
});
defineEmits(["evidence", "retry-evidence"]);
const tab = ref("report"), selectedNode = ref(""), selectedId = ref(""), selectedCandidateId = ref("");
const cursor = ref(0), playing = ref(false);
const followStatus = ref(true), followingLatest = ref(true), restoreCursorId = ref("");
let timer;
const records = computed(() => evidenceRows(props.evidence, props.investigation));
const graph = computed(() => topology(records.value, props.diagnosis?.asset_registration || { allowed_services: [] }));
const candidates = computed(() => visualCandidates(props.investigation, props.diagnosis, props.hypotheses));
const facts = computed(() => reportFacts(props.diagnosis, records.value));
const healthyChecks = computed(() => props.diagnosis?.kind === 'healthy_within_scope'
  ? records.value.filter(row => ['services', 'ports', 'dependency_probe'].includes(row.kind)) : []);
const actions = computed(() => reportActions(props.diagnosis));
const comparedEndpoints = computed(() => props.status === "pending_review" ? [] : endpointComparison(props.diagnosis, records.value));
const overview = computed(() => reportOverview(props.diagnosis, records.value));
const leadEvidence = computed(() => {
  const ids = new Set((props.diagnosis?.evidence || []).map(item => item.evidence_id));
  const cited = records.value.filter(row => ids.has(row.id));
  return ['configuration', 'dependency_probe', 'text_logs']
    .map(kind => cited.find(row => row.kind === kind)).filter(Boolean);
});
const currentCandidates = computed(() => candidates.value.filter(row => row.status !== "dropped")
  .sort((a, b) => Number(b.status === "confirmed") - Number(a.status === "confirmed")));
const pastCandidates = computed(() => candidates.value.filter(row => row.status === "dropped"));
function actionTitle(action) {
  if (props.diagnosis?.kind === "confirmed_cause" && props.diagnosis.root_cause_code === "registered_service_stopped"
      && action.scope?.service === props.diagnosis.cause_subject)
    return `请运维人员恢复${serviceLabel(action.scope.service)}，再复测原来失败的操作`;
  if (props.diagnosis?.kind === "confirmed_cause" && props.diagnosis.root_cause_code === "downstream_stopped_after_request" && /启动|恢复/.test(action.action))
    return "请运维人员恢复下游服务";
  return readableText(action.action);
}
const tabs = computed(() => [
  { id: "report", name: "诊断报告" }, { id: "process", name: "排查过程" },
  { id: "evidence", name: "现场证据", count: records.value.length }, { id: "causes", name: "候选原因", count: candidates.value.length },
]);
const conclusionLabel = computed(() => props.status === "pending_review" ? "报告草稿待复核" : ({
  confirmed_cause: "原因已确认", localized_fault: "故障层已定位 · 原因待确认",
  unlocated: "尚未定位", healthy_within_scope: "本次范围内未发现故障",
}[props.diagnosis?.kind] || ({ running: "正在诊断", pending_review: "报告草稿待复核", failed: "诊断失败，保留已有材料", disconnected: "进度连接已断开" }[props.status] || (props.status === "completed" ? "诊断已完成" : "等待诊断结果"))));
const current = computed(() => records.value[cursor.value]);
const replayGraph = computed(() => {
  const visible = new Set(records.value.slice(0, cursor.value + 1).map((row) => row.id));
  return { nodes: graph.value.nodes.map((node) => ({ ...node, evidence: node.evidence.filter((row) => visible.has(row.id)) })),
    edges: graph.value.edges.filter((edge) => visible.has(edge.evidence)) };
});
const activeNode = computed(() => graph.value.nodes.find((node) => node.id === selectedNode.value) ||
  (graph.value.nodes.filter((node) => node.service === selectedNode.value).length === 1
    ? graph.value.nodes.find((node) => node.service === selectedNode.value) : null) ||
  graph.value.nodes.find((node) => node.evidence.some((row) => row.id === facts.value[0]?.id)) ||
  graph.value.nodes.find((node) => node.id === facts.value[0]?.object || node.service === facts.value[0]?.object) || graph.value.nodes[0]);
const selectedRecord = computed(() => selectedId.value ? records.value.find((row) => row.id === selectedId.value) : records.value[0]);
const selectedCandidate = computed(() => candidates.value.find((row) => row.id === selectedCandidateId.value) ||
  candidates.value.find((row) => props.diagnosis?.kind === "confirmed_cause" && row.id === props.diagnosis.hypothesis_id) ||
  candidates.value.find((row) => row.id === props.investigation?.leading_id) || candidates.value[0]);
const groups = computed(() => graph.value.nodes.filter(node => node.evidence.length));
const evidenceState = ref(""), evidenceGroup = ref("");
const chartFilter = computed(() => groups.value.find(node => node.id === evidenceGroup.value));
const evidenceFilters = computed(() => [
  { id: "", label: "全部", count: records.value.length },
  ...[["abnormal", "发现异常"], ["observed", "已采集"], ["partial", "部分结果"], ["unavailable", "未取得"]]
    .map(([id, label]) => ({ id, label, count: records.value.filter(row => row.state === id).length }))
    .filter(item => item.count),
]);
const filteredGroups = computed(() => {
  const term = evidenceQuery.value.trim().toLowerCase();
  return groups.value.filter(node => !evidenceGroup.value || node.id === evidenceGroup.value).map(node => ({ ...node, evidence: node.evidence.filter(row =>
    (!evidenceState.value || row.state === evidenceState.value) &&
    (!term || [node.label, row.label, row.title, row.result].some(text => text?.toLowerCase().includes(term))),
  ) })).filter(node => node.evidence.length);
});
function clearEvidenceFilters() { evidenceQuery.value = ""; evidenceState.value = ""; evidenceGroup.value = ""; }
const candidateStatuses = computed(() => [...new Set(candidates.value.map(row => row.statusLabel))]
  .map(label => ({ label, count: candidates.value.filter(row => row.statusLabel === label).length })));
const excludedCandidates = computed(() => candidates.value.filter(row => row.status === 'excluded'));
const selectedIsHidden = computed(() => selectedRecord.value && !filteredGroups.value.some(group => group.evidence.some(row => row.id === selectedRecord.value.id)));
const candidateLinks = computed(() => (selectedCandidate.value?.relations || []).map((link) => ({ ...link, record: records.value.find((row) => row.id === link.id) })));
const mainCandidateLinks = computed(() => selectedCandidate.value?.status === "confirmed" && overview.value.steps.length
  ? overview.value.steps.map(step => candidateLinks.value.find(link => link.id === step.id)).filter(Boolean) : candidateLinks.value);
const otherCandidateLinks = computed(() => candidateLinks.value.filter(link => !mainCandidateLinks.value.includes(link)));
const relationLabel = (value) => ({ citation: "结论依据", support: "支持", contradict: "反驳", neutral: "关联记录 · 关系未定" }[value] || "关系未定");
const questions = computed(() => reportQuestions(props.diagnosis));
const selectedEvents = computed(() => logEvents(selectedRecord.value?.payload));
function selectTab(value) { followStatus.value = false; if (value !== "evidence") evidenceOrigin.value = null; tab.value = value; }
const panel = ref(null), evidenceIndex = ref(null), evidenceDetail = ref(null);
const evidenceOrigin = ref(null);
const evidenceQuery = ref("");
async function goTab(value) {
  selectTab(value);
  await nextTick();
  panel.value?.focus();
}
defineExpose({ showReport: () => goTab('report') });
async function openEvidence(id) {
  if (tab.value !== 'evidence') {
    evidenceOrigin.value = { tab: tab.value, trigger: document.activeElement };
    clearEvidenceFilters();
    selectedId.value = id;
    await goTab('evidence');
  } else selectedId.value = id;
}
async function openChartGroup(id) {
  const group = groups.value.find(node => node.id === id);
  if (!group) return;
  const row = group.evidence.find(item => item.state === "abnormal") || group.evidence[0];
  const navigation = openEvidence(row.id);
  evidenceGroup.value = id;
  await navigation;
}
async function openEvidenceNode(id) {
  await openEvidence(id);
  await nextTick();
  evidenceDetail.value?.focus();
}
async function returnFromEvidence() {
  const origin = evidenceOrigin.value;
  if (!origin) return;
  await goTab(origin.tab);
  if (origin.trigger?.isConnected && panel.value?.contains(origin.trigger)) origin.trigger.focus();
}
function selectCandidate(id) { followStatus.value = false; selectedCandidateId.value = id; }
function selectNode(id) { followStatus.value = false; selectedNode.value = id; }
function pause() { clearInterval(timer); timer = undefined; playing.value = false; }
function seek(index) { pause(); restoreCursorId.value = ""; followingLatest.value = false; cursor.value = Math.max(0, Math.min(records.value.length - 1, index)); }
function followLatest() { pause(); restoreCursorId.value = ""; followingLatest.value = true; cursor.value = Math.max(0, records.value.length - 1); }
function selectReplayNode(name) {
  selectNode(name);
  const id = replayGraph.value.nodes.find(node => node.id === name)?.evidence.at(-1)?.id;
  if (id) seek(records.value.findIndex(row => row.id === id));
}
function play() {
  if (playing.value) return pause();
  if (records.value.length < 2) return;
  restoreCursorId.value = ""; followingLatest.value = false;
  if (cursor.value >= records.value.length - 1) cursor.value = 0;
  playing.value = true;
  timer = setInterval(() => {
    cursor.value += 1;
    if (cursor.value >= records.value.length - 1) pause();
  }, 1600);
}
function keyboardTabs(event) {
  const buttons = [...event.currentTarget.querySelectorAll('[role="tab"]')];
  const index = buttons.indexOf(document.activeElement);
  let next;
  if (event.key === "ArrowRight") next = (index + 1) % buttons.length;
  if (event.key === "ArrowLeft") next = (index + buttons.length - 1) % buttons.length;
  if (event.key === "Home") next = 0;
  if (event.key === "End") next = buttons.length - 1;
  if (next != null) { event.preventDefault(); buttons[next].click(); buttons[next].focus(); }
}
watch(tab, () => pause());
watch([() => props.runId, () => session.user?.id], () => {
  pause(); cursor.value = 0; clearEvidenceFilters(); evidenceOrigin.value = null;
  const saved = readWorkspace(session.user?.id, props.runId);
  const text = key => typeof saved?.[key] === "string" ? saved[key] : "";
  selectedId.value = text("evidenceId"); selectedNode.value = text("nodeId"); selectedCandidateId.value = text("candidateId");
  restoreCursorId.value = text("cursorId"); followStatus.value = saved?.followStatus !== false;
  followingLatest.value = saved?.followingLatest ?? saved?.followStatus ?? true;
  tab.value = saved?.tab || (props.status === "running" ? "process" : "report");
  const index = records.value.findIndex(row => row.id === restoreCursorId.value);
  if (props.status === "running" && followingLatest.value) { cursor.value = Math.max(0, records.value.length - 1); restoreCursorId.value = ""; }
  else if (index >= 0) { cursor.value = index; restoreCursorId.value = ""; }
}, { immediate: true });
watch(() => props.status, (value) => {
  if (!followStatus.value) return;
  if (value === "completed" || value === "pending_review") tab.value = "report";
  if (value === "running") tab.value = "process";
});
watch(() => records.value.map(row => row.id), (ids, previous) => {
  const restored = ids.indexOf(restoreCursorId.value);
  const retained = ids.indexOf(previous[cursor.value]);
  if (props.status === "running" && followingLatest.value) { cursor.value = Math.max(0, ids.length - 1); restoreCursorId.value = ""; }
  else if (restored >= 0) { cursor.value = restored; restoreCursorId.value = ""; }
  else if (retained >= 0) cursor.value = retained;
  else if (cursor.value >= ids.length) { pause(); cursor.value = Math.max(0, ids.length - 1); }
});
watch([cursor, tab], async () => {
  if (tab.value !== "process") return;
  await nextTick();
  const list = panel.value?.querySelector('.check-list');
  const row = list?.querySelector('[aria-current="step"]');
  if (!row || !list.getBoundingClientRect) return;
  const parent = list.getBoundingClientRect(), item = row.getBoundingClientRect();
  if (item.top < parent.top) list.scrollTop += item.top - parent.top;
  else if (item.bottom > parent.bottom) list.scrollTop += item.bottom - parent.bottom;
});
watch([selectedId, tab], async () => {
  if (tab.value !== 'evidence' || !selectedId.value) return;
  await nextTick();
  const list = evidenceIndex.value;
  const row = list?.querySelector('[aria-pressed="true"]');
  if (!row) return;
  const parent = list.getBoundingClientRect(), item = row.getBoundingClientRect();
  if (item.top < parent.top) list.scrollTop += item.top - parent.top;
  else if (item.bottom > parent.bottom) list.scrollTop += item.bottom - parent.bottom;
});
watch([tab, selectedId, selectedNode, selectedCandidateId, cursor, followStatus, followingLatest], () => {
  writeWorkspace(session.user?.id, props.runId, { tab: tab.value, evidenceId: selectedId.value, nodeId: selectedNode.value,
    candidateId: selectedCandidateId.value, cursorId: restoreCursorId.value || current.value?.id || "", followStatus: followStatus.value, followingLatest: followingLatest.value });
}, { flush: "post" });
onUnmounted(pause);
</script>

<template>
  <div class="diagnostic-workspace">
    <nav class="workspace-tabs" role="tablist" aria-label="诊断内容" @keydown="keyboardTabs">
      <button v-for="item in tabs" :id="`diagnosis-tab-${item.id}`" :key="item.id" role="tab"
        :aria-controls="`diagnosis-panel-${item.id}`" :aria-selected="tab === item.id" :tabindex="tab === item.id ? 0 : -1"
        :class="{ active: tab === item.id }" @click="selectTab(item.id)">{{ item.name }}<span v-if="item.count != null">{{ item.count }}</span></button>
    </nav>
    <section ref="panel" tabindex="-1" :id="`diagnosis-panel-${tab}`" role="tabpanel" :aria-labelledby="`diagnosis-tab-${tab}`" class="workspace-panel">
      <div v-if="tab === 'report' || evidenceOrigin?.tab === 'report'" v-show="tab === 'report'">
        <template v-if="diagnosis || report">
          <header :class="['report-lead', { healthy: status !== 'pending_review' && diagnosis?.kind === 'healthy_within_scope', 'has-lead-evidence': leadEvidence.length }]">
            <div class="lead-summary">
            <span :class="['conclusion-label', { confirmed: status !== 'pending_review' && diagnosis?.kind === 'confirmed_cause' }]">{{ conclusionLabel }}</span>
            <h2>{{ overview.title }}</h2>
            <p v-if="records.length || usage?.elapsed_s != null" class="report-scope"><span v-if="records.length">{{ records.length }} 项现场证据</span><span v-if="usage?.elapsed_s != null">{{ records.length ? ' · ' : '' }}用时 {{ Math.round(usage.elapsed_s) }} 秒</span></p>
            </div>
            <section v-if="leadEvidence.length" class="lead-evidence" aria-label="报告引用">
              <h3>报告引用</h3>
              <button v-for="row in leadEvidence" :key="row.id" type="button" @click="openEvidence(row.id)">
                <code>{{ row.label }}</code><span>{{ row.title }}</span><Icon name="arrow" :size="15" />
              </button>
            </section>
          </header>
          <DiagnosisCharts v-if="records.length" :groups="groups" :records="records" @group="openChartGroup" @evidence="openEvidence" />
          <section v-if="comparedEndpoints.length" class="service-map endpoint-map" aria-label="连接端口对照">
            <div class="map-heading"><div><h3>连接端口对照</h3><p>点开任一端口，查看本次连接探测记录。</p></div></div>
            <div class="endpoint-comparison">
              <button v-for="item in comparedEndpoints" :key="item.evidence" type="button" :class="item.tone" @click="openEvidence(item.evidence)">
                <span class="endpoint-icon"><Icon :name="item.tone === 'failed' ? 'close' : 'server'" :size="20" /></span>
                <span class="endpoint-port"><span>{{ item.label }}</span><strong>{{ item.port }}</strong></span>
                <span class="endpoint-result">{{ item.detail }}</span><Icon name="arrow" :size="16" />
              </button>
            </div>
          </section>
          <section v-if="records.length && graph.nodes.length" class="service-map" aria-label="现场服务拓扑">
            <div class="map-heading">
              <div><h3>现场服务拓扑</h3><p>{{ graph.edges.length ? "连线表示已登记或观测到的依赖，不等同于故障传播。" : "本次没有可绘制的依赖连线；点击节点可查看各自的现场观测。" }}</p></div>
              <span v-if="graph.nodes.some(node => node.evidence.some(row => row.state === 'abnormal'))" class="map-key">红色标记：存在异常观测</span>
            </div>
            <DiagnosisTopology :graph="graph" :selected="activeNode?.id" @select="selectNode" @evidence="openEvidence" />
            <div v-if="activeNode" class="map-evidence">
              <h4>{{ activeNode.label || serviceLabel(activeNode.service || activeNode.id) }} · 现场观测</h4>
              <p v-if="!activeNode.evidence.length" class="muted">该对象暂无独立观测。</p>
              <div v-else class="map-observations">
                <button v-for="row in activeNode.evidence" :key="row.id" class="text-button" @click="openEvidence(row.id)">
                  <code>{{ row.label }}</code> {{ row.title }} <Icon name="arrow" :size="14" />
                </button>
              </div>
            </div>
          </section>
          <h3 v-if="diagnosis && !overview.steps.length">{{ healthyChecks.length ? '本次已检查的对象' : '现场发现' }}</h3><p v-if="diagnosis && !facts.length && !overview.steps.length && !healthyChecks.length">{{ diagnosis?.kind === 'healthy_within_scope' ? '本次已检查的对象和时间内未发现异常，不能代表所有功能长期正常。' : '当前证据尚未形成可确认的故障事实。' }}</p>
          <ul v-if="healthyChecks.length" class="checked-paths" aria-label="本次实际检查"><li v-for="row in healthyChecks" :key="row.id"><button class="text-button" @click="openEvidence(row.id)">{{ row.label }} · {{ row.title }}</button><span>{{ row.result }}</span></li></ul>
          <section v-if="overview.steps.length" class="failure-story" aria-label="故障影响过程">
            <h3>故障怎么影响用户</h3>
            <ol class="failure-flow"><li v-for="(step, index) in overview.steps" :key="step.id" :class="step.tone">
              <button @click="openEvidence(step.id)" :aria-label="`${step.object}：${step.title}，查看证据`">
                <span class="flow-symbol"><Icon :name="step.icon" :size="24" /></span>
                <span class="flow-object">{{ step.object }}</span><strong>{{ step.title }}</strong>
                <span class="flow-source">{{ records.find(row => row.id === step.id)?.label }} · 查看证据<Icon name="arrow" :size="14" /></span>
              </button><Icon v-if="index < overview.steps.length - 1" class="flow-arrow" name="arrow" :size="22" />
            </li></ol>
          </section>
          <div v-else-if="facts.length" class="fact-strip" aria-label="已发现的异常">
            <button v-for="fact in facts" :key="fact.id" @click="openEvidence(fact.id)"><span>{{ serviceLabel(fact.object) }}</span><strong>{{ fact.text }}</strong><Icon name="arrow" :size="16" /></button>
          </div>
          <div v-if="actions.length" class="next-actions"><h3>接下来怎么做<span>尚未执行</span></h3>
            <details v-for="(action, index) in actions" :key="JSON.stringify([action.target, action.action, action.scope])" class="action-row">
              <summary><span class="sequence">{{ String(index + 1).padStart(2, '0') }}</span><span>{{ actionTitle(action) }}</span><Icon name="down" :size="16" /></summary>
              <div class="action-content"><p v-if="action.target">目标主机：{{ action.target }}</p><p v-if="actionTitle(action) !== action.action">{{ action.action }}</p><template v-for="section in [{ title: '操作前确认', rows: action.preconditions }, { title: '操作影响', rows: action.risks }, { title: '恢复后检查', rows: action.verification }]" :key="section.title">
                <template v-if="section.rows.length"><h4>{{ section.title }}</h4><ul><li v-for="text in section.rows" :key="text">{{ text }}</li></ul></template>
              </template><div v-if="action.evidence.length" class="evidence-chips"><span>建议依据</span><button v-for="id in action.evidence" :key="id" @click="openEvidence(id)">{{ records.find(row => row.id === id)?.label || '引用未加载' }}</button></div></div>
            </details>
          </div>
          <div v-else-if="diagnosis?.kind === 'healthy_within_scope'" class="next-actions"><h3>接下来怎么做</h3><p>本次已检查路径未发现故障。若再次出现异常，请记录发生时间、网址和具体操作，再检查对应失败路径；未覆盖功能仍需分别验证。</p></div>
          <section v-if="diagnosis" class="findings-summary" aria-label="结论边界">
            <h3>结论边界</h3>
            <div class="finding-columns">
              <div><h4>已排除的事项</h4><ul v-if="excludedCandidates.length">
                <li v-for="candidate in excludedCandidates" :key="candidate.id">{{ candidate.text }}
                  <button v-if="candidate.evidence.length" class="text-button" @click="openEvidence(candidate.evidence[0])">查看依据</button>
                </li>
              </ul><p v-else class="muted">尚无满足证据标准的排除结论。</p></div>
              <div><h4>尚未查清的事</h4><ul v-if="questions.length">
                <li v-for="(question, index) in questions" :key="question.id || index">{{ question.text }}
                  <details v-if="question.reason" class="question-boundary"><summary>对当前结论的影响（模型判断）</summary><p>以下理由仍未独立核验：{{ readableText(question.reason) }}</p></details>
                </li>
              </ul><p v-else class="muted">未覆盖的业务路径、时间及历史原因仍不能确定。</p></div>
            </div>
            <details v-if="diagnosis.limitations?.length" class="evidence-limits">
              <summary>证据范围与校验限制（{{ diagnosis.limitations.length }} 项）</summary>
              <ul><li v-for="(text, index) in diagnosis.limitations" :key="index">{{ readableText(text) }}</li></ul>
            </details>
          </section>
          <KnowledgeReferences v-if="knowledgeReferences.length" :references="knowledgeReferences" />
          <details v-if="report || diagnosis" class="report-fold"><summary>完整报告与技术详情</summary><p>以下保留模型原始叙述，其中自由文本的因果解释未经逐句核验；确认等级及证据边界见上方结论。</p><p v-if="diagnosis?.scope">{{ diagnosis.scope }}</p><Markdown v-if="report" :content="report" @evidence="openEvidence" /><p v-else>{{ diagnosis?.conclusion }}</p></details>
        </template>
        <div v-else class="workspace-empty"><Icon name="pulse" :size="36" /><span>{{ statusText || '尚无诊断报告' }}</span></div>
        <slot name="experience" />
      </div>
      <div v-if="tab === 'process' || evidenceOrigin?.tab === 'process'" v-show="tab === 'process'">
        <p v-if="snapshotError" class="workspace-note" role="status">{{ snapshotError }}；现场证据与工具记录仍可单独查看。</p>
        <div class="replay-toolbar"><div><h3>{{ status === 'running' ? '现场采集进度' : '现场采集回放' }}</h3><span v-if="records.length">{{ cursor + 1 }} / {{ records.length }} 项现场记录</span></div>
          <div v-if="records.length" class="replay-controls"><button v-if="status === 'running'" class="button" :aria-pressed="followingLatest" @click="followLatest">跟随最新</button><button class="button" :disabled="!records.length || cursor === 0" @click="seek(cursor - 1)" aria-label="上一项" title="上一项观测"><Icon name="arrowLeft" :size="16" /></button>
            <button v-if="status !== 'running'" class="button" :disabled="records.length < 2" :aria-pressed="playing" @click="play">{{ playing ? '暂停' : cursor === records.length - 1 && records.length ? '重新回放' : '回放' }}</button>
            <button class="button" :disabled="!records.length || cursor === records.length - 1" @click="seek(cursor + 1)" aria-label="下一项" title="下一项观测"><Icon name="arrow" :size="16" /></button></div>
        </div>
        <div v-if="records.length" class="process-split">
          <div class="timeline-board"><header class="visual-heading"><Icon name="clock" :size="18" /><div><h3>采集时间线</h3><p>按实际采集顺序排列，点击节点查看当时的观测。</p></div></header>
          <ol class="check-list" aria-label="实际采集顺序"><li v-for="(row, index) in records" :key="row.id"><button :class="{ selected: cursor === index }" :aria-current="cursor === index ? 'step' : undefined" @click="seek(index)">
            <span :class="['check-number', row.state]">{{ String(index + 1).padStart(2, '0') }}</span><span class="check-copy"><strong>{{ row.title }}</strong><small>{{ row.result }}</small><time v-if="row.time" :datetime="row.time">{{ clockTime(row.time) }}</time></span>
          </button></li></ol></div>
          <div class="replay-scene visual-board">
            <div v-if="current" class="current-observation" :aria-live="playing ? 'off' : 'polite'"><span>{{ current.label }} · {{ clockTime(current.time) }}</span><span :class="['observation-state', current.state]">{{ current.stateLabel }}</span><h3>{{ current.title }}</h3><p>{{ current.result }}</p><button class="text-button" @click="openEvidence(current.id)">查看证据<Icon name="arrow" :size="16" /></button></div>
            <details v-if="replayGraph.nodes.length" class="report-fold"><summary>当前采集关系图</summary><DiagnosisTopology :graph="replayGraph" :current="current?.id" :selected="selectedNode" @select="selectReplayNode" @evidence="openEvidence" /></details>
          </div>
        </div>
        <div v-else class="workspace-empty">{{ status === 'running' ? statusText || '正在获取现场观测' : '暂无现场采集记录' }}</div>
        <details v-if="plans.length" class="report-fold"><summary>排查计划 · {{ plans.filter(plan => plan.done).length }}/{{ plans.length }} 项完成</summary><ol class="plan-list"><li v-for="(plan, index) in plans" :key="index"><span>{{ plan.text }}</span><span class="muted">{{ plan.done ? '已完成' : '未完成' }}</span></li></ol></details>
        <slot name="audit" />
        <details v-if="diagnosis?.stop_reason || investigation?.stop_reason" class="report-fold"><summary>排查结束记录</summary><p>{{ diagnosis?.stop_reason || investigation?.stop_reason }}</p></details>
      </div>
      <template v-if="tab === 'evidence'">
        <div v-if="evidenceOrigin || evidenceError" class="evidence-tools">
          <button v-if="evidenceOrigin" class="text-button" @click="returnFromEvidence"><Icon name="arrowLeft" :size="16" />返回{{ tabs.find(item => item.id === evidenceOrigin.tab)?.name }}</button>
          <div v-if="evidenceError" role="alert" class="evidence-error"><span>证据读取失败：{{ evidenceError }}</span><button class="text-button" @click="$emit('retry-evidence')">重读证据</button></div>
        </div>
        <div v-if="!records.length && !evidenceError" class="workspace-empty">{{ selectedId ? '引用的现场证据暂不可读' : '尚无现场证据' }}</div>
        <section v-if="records.length" class="review-summary" aria-label="现场证据概览">
          <div><h3>证据台账</h3><p>按采集状态筛选；「已采集」不代表服务正常。</p></div>
          <div class="review-pills" role="group" aria-label="按采集状态筛选">
            <button v-for="item in evidenceFilters" :key="item.id" type="button" :class="item.id" :aria-pressed="evidenceState === item.id" @click="evidenceState = item.id">{{ item.label }} <strong>{{ item.count }}</strong></button>
          </div>
        </section>
        <div v-if="records.length" class="evidence-split"><div class="evidence-sidebar">
          <header class="visual-heading"><Icon name="workflow" :size="18" /><div><h3>现场证据图</h3><p>按服务分组；选择编号查看具体记录。</p></div></header>
          <div v-if="chartFilter" class="chart-filter"><span>仅看：{{ chartFilter.label }}</span><button type="button" class="text-button" @click="evidenceGroup = ''">查看全部对象</button></div>
          <label class="search-input"><Icon name="search" :size="16" /><input v-model="evidenceQuery" type="search" aria-label="筛选现场证据" placeholder="按对象、编号或观测筛选" /></label>
          <p v-if="!filteredGroups.length" class="muted" role="status">没有匹配的证据</p>
          <nav ref="evidenceIndex" class="evidence-index evidence-map" aria-label="按对象选择证据">
            <section v-for="group in filteredGroups" :key="group.id">
              <h3><Icon name="server" :size="16" />{{ group.label || serviceLabel(group.service || group.id) }}<span>{{ group.evidence.length }} 条</span></h3>
              <div class="evidence-nodes">
                <button v-for="row in group.evidence" :key="row.id" type="button" :class="[row.state, { selected: selectedRecord?.id === row.id }]"
                  :aria-pressed="selectedRecord?.id === row.id" :aria-label="`${row.label} · ${row.title} · ${row.stateLabel}`" :title="`${row.title} · ${row.stateLabel}`" @click="openEvidenceNode(row.id)">
                  <span :class="['evidence-code', row.state]">{{ row.label }}</span><span>{{ row.kindLabel }}</span>
                </button>
              </div>
            </section>
          </nav>
        </div>
          <article v-if="selectedRecord" ref="evidenceDetail" class="evidence-detail" tabindex="-1" aria-label="当前证据详情"><header class="evidence-heading"><div><span class="eyebrow">{{ selectedRecord.label }} · {{ clockTime(selectedRecord.time) }}</span><h2>{{ selectedRecord.title }}</h2></div><div class="evidence-heading-actions"><span :class="['observation-state', selectedRecord.state]">{{ selectedRecord.stateLabel }}</span><button class="button source-button" @click="$emit('evidence', selectedRecord.id)">来源与原文<Icon name="arrow" :size="16" /></button></div></header>
            <p v-if="selectedIsHidden" class="muted">当前证据不在筛选结果中。 <button class="text-button" @click="clearEvidenceFilters">清除筛选</button></p>
            <p class="evidence-result">{{ selectedRecord.result }}</p>
            <ol v-if="selectedEvents.length" class="event-chain"><li v-for="event in selectedEvents" :key="event.index"><time>{{ clockTime(event.time) }}</time><div><strong>{{ event.label }}</strong><p v-if="event.text">{{ event.text }}</p><details v-if="event.data && ['pid', 'request_id', 'instance_id'].some(key => event.data[key] != null)" class="event-identifiers"><summary>定位信息</summary><dl><template v-for="field in ['pid', 'request_id', 'instance_id']" :key="field"><template v-if="event.data[field] != null"><dt>{{ {pid:'进程号',request_id:'请求编号',instance_id:'实例编号'}[field] }}</dt><dd>{{ event.data[field] }}</dd></template></template></dl></details></div></li></ol>
            <dl v-else-if="selectedRecord.kind === 'configuration' && selectedRecord.payload" class="payload-table"><template v-for="(value, key) in selectedRecord.payload.values || {}" :key="key"><dt>{{ fieldLabel(key) }}</dt><dd><pre v-if="value !== null && typeof value === 'object'">{{ JSON.stringify(value, null, 2) }}</pre><template v-else>{{ value ?? '—' }}</template></dd></template></dl>
            <div v-else-if="selectedRecord.kind === 'processes' && selectedRecord.payload?.processes?.length" class="payload-table-wrap"><table><thead><tr><th>PID</th><th>进程</th><th>内存</th></tr></thead><tbody><tr v-for="process in selectedRecord.payload.processes" :key="process.pid"><td>{{ process.pid }}</td><td>{{ process.name }}</td><td>{{ process.memory_bytes != null ? `${(process.memory_bytes / 1024 / 1024).toFixed(1)} MB` : '—' }}</td></tr></tbody></table></div>
            <section v-if="selectedRecord.kind === 'configuration' && selectedRecord.payload?.static_mounts?.length" class="resource-mapping" aria-label="资源目录实际映射">
              <h3>网站实际使用的资源目录</h3>
              <dl v-for="mapping in selectedRecord.payload.static_mounts" :key="mapping.destination" class="payload-table">
                <dt>网站内的目录</dt><dd>{{ mapping.destination }}</dd>
                <dt>登记的来源目录</dt><dd>{{ mapping.registered_source }}</dd>
                <dt>实际使用的来源目录</dt><dd>{{ mapping.actual_source || '未发现对应映射' }}</dd>
                <template v-for="(present, resource) in mapping.registered_resources_present || {}" :key="resource"><dt>登记目录中的 {{ resource }}</dt><dd>{{ present === true ? '文件存在' : present === false ? '文件不存在' : '尚未确定' }}</dd></template>
              </dl>
            </section>
          </article>
          <p v-else role="alert">该引用的现场证据尚未读取或已不可用，请重新载入证据台账后核对。</p>
        </div>
      </template>
      <div v-if="tab === 'causes' || evidenceOrigin?.tab === 'causes'" v-show="tab === 'causes'">
        <div v-if="!candidates.length" class="workspace-empty">暂无候选原因</div>
        <section v-if="candidates.length" class="review-summary" aria-label="候选原因概览">
          <div><h3>候选判断</h3><p>停止排查不等于已排除；有支持证据也不等于已确认。</p></div>
          <div class="review-pills"><span v-for="item in candidateStatuses" :key="item.label">{{ item.label }} <strong>{{ item.count }}</strong></span></div>
        </section>
        <div v-if="candidates.length" class="cause-split"><nav class="candidate-index" aria-label="选择候选原因"><header class="visual-heading"><Icon name="chart" :size="18" /><div><h3>候选节点</h3><p>选择候选，查看它对应的证据关系图。</p></div></header><button v-for="candidate in currentCandidates" :key="candidate.id" :class="{ selected: selectedCandidate?.id === candidate.id }" :aria-pressed="selectedCandidate?.id === candidate.id" @click="selectCandidate(candidate.id)">
          <span class="candidate-meta">{{ candidate.number }} · {{ candidate.type }}<span :class="candidate.status">{{ candidate.statusLabel }}</span></span><strong>{{ candidate.text }}</strong>
        </button><details v-if="pastCandidates.length" class="candidate-history" :open="pastCandidates.some(row => row.id === selectedCandidate?.id) || undefined"><summary>此前排查 · {{ pastCandidates.length }}</summary><button v-for="candidate in pastCandidates" :key="candidate.id" :class="{ selected: selectedCandidate?.id === candidate.id }" :aria-pressed="selectedCandidate?.id === candidate.id" @click="selectCandidate(candidate.id)"><span class="candidate-meta">{{ candidate.number }}<span>{{ candidate.statusLabel }}</span></span><strong>{{ candidate.text }}</strong></button></details></nav>
          <article v-if="selectedCandidate" class="candidate-detail"><header class="candidate-root"><Icon name="workflow" :size="20" /><div><span class="eyebrow">{{ selectedCandidate.number }} · {{ selectedCandidate.type }}</span><h2>{{ selectedCandidate.text }}</h2><span :class="['conclusion-label', { confirmed: selectedCandidate.status === 'confirmed' }]">{{ selectedCandidate.statusLabel }}</span></div></header>
            <div v-if="candidateLinks.length" class="candidate-graph" aria-label="证据与候选关系"><div class="relation-junction"><span><Icon name="workflow" :size="14" /> 关联现场证据 · {{ candidateLinks.length }} 条</span></div><p class="relation-note">线条只表示与当前候选有关；标签说明依据、支持、反驳或关系未定。</p><div class="relation-evidence relation-map"><button v-for="link in mainCandidateLinks" :key="link.id" :class="['relation-node', link.relation]" @click="openEvidence(link.id)"><span>{{ link.record?.label || '证据' }} · {{ relationLabel(link.relation) }}</span><strong>{{ link.record?.title || '证据尚不可读' }}</strong><small v-if="link.record">{{ link.record.result }}</small><Icon class="relation-open" name="arrow" :size="14" /></button></div></div>
            <p v-if="!candidateLinks.length" class="relation-empty">尚无关联的现场证据。</p>
            <details v-if="otherCandidateLinks.length" class="report-fold other-evidence"><summary>其他依据 · {{ otherCandidateLinks.length }}</summary><div class="relation-evidence"><button v-for="link in otherCandidateLinks" :key="link.id" :class="['relation-node', link.relation]" @click="openEvidence(link.id)"><span>{{ link.record?.label || '证据' }} · {{ relationLabel(link.relation) }}</span><strong>{{ link.record?.title || '现场记录' }}</strong><small v-if="link.record">{{ link.record.result }}</small></button></div></details>
            <div v-if="!['confirmed', 'supported', 'excluded', 'dropped'].includes(selectedCandidate.status) && (selectedCandidate.question || selectedCandidate.nextCheck)" class="candidate-gap"><h3>待核实</h3><p v-if="selectedCandidate.question">{{ selectedCandidate.question }}</p><p v-if="selectedCandidate.nextCheck && selectedCandidate.nextCheck !== selectedCandidate.question"><strong>拟核查：</strong>{{ selectedCandidate.nextCheck }}</p></div>
            <details v-if="selectedCandidate.limitation" class="report-fold"><summary>判断依据与保留项</summary><p>{{ selectedCandidate.limitation }}</p></details>
            <details v-if="selectedCandidate.original && selectedCandidate.original !== selectedCandidate.text" class="report-fold"><summary>候选原始描述</summary><p>{{ selectedCandidate.original }}</p></details>
          </article>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.diagnostic-workspace { min-width: 0; color: #323130; }
.workspace-tabs { display: flex; flex-wrap: wrap; gap: 4px 8px; border-bottom: 1px solid var(--desk-line, #e8e7e5); }
.workspace-tabs button { display: flex; gap: 8px; align-items: center; border: 0; border-bottom: 2px solid transparent; background: transparent; padding: 12px 14px; font: inherit; color: #4c5b6e; cursor: pointer; white-space: nowrap; border-radius: 7px 7px 0 0; }
.workspace-tabs button:hover, .workspace-tabs button.active { background: #edf3fb; }
.workspace-tabs button.active { color: #14539a; border-color: currentColor; font-weight: 700; }
.workspace-tabs span { color: #485a71; font: 600 11px/1.5 ui-monospace, Consolas, monospace; background: #e9eef5; border-radius: 4px; padding: 0 4px; }
.workspace-panel { padding-top: 20px; }
h2 { font-size: 24px; line-height: 1.5; font-weight: 600; margin: 12px 0; overflow-wrap: anywhere; }
h3 { margin: 0 0 16px; font-size: 14px; font-weight: 600; }
h4 { font-size: 13px; margin: 16px 0 8px; }
p { line-height: 1.7; overflow-wrap: anywhere; }
.conclusion-label { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: #9b6700; }
.conclusion-label::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: #bf8b00; }
.conclusion-label.confirmed { color: #107c41; }.conclusion-label.confirmed::before { background: #107c41; }
.report-lead { --lead-color: #184e86; --lead-bg: #f0f5fc; display: grid; gap: 18px 32px; padding: clamp(18px, 2.5vw, 28px); margin-bottom: 20px; border: 1px solid var(--desk-line, #d9e3ef); border-inline-start: 4px solid var(--lead-color); border-radius: 10px; background: var(--lead-bg); color: #172e47; }
.report-lead.healthy { --lead-color: #1d6a52; --lead-bg: #edf7f3; }
.report-lead.has-lead-evidence { grid-template-columns: minmax(0, 1fr) minmax(225px, 34%); }
.lead-summary { align-self: center; min-width: 0; }
.report-lead .conclusion-label { font-weight: 700; }
.report-lead.healthy .conclusion-label { color: #1d6a52; }
.report-lead.healthy .conclusion-label::before { background: currentColor; }
.report-scope { color: #465a71; font-size: 13px; margin: 0; }
.lead-evidence { min-width: 0; border-inline-start: 1px solid #ccd9e9; padding-inline-start: 20px; }
.lead-evidence h3 { color: #3e526b; margin: 0 0 6px; font-size: 13px; }
.lead-evidence button { display: grid; width: 100%; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px; align-items: center; background: transparent; border: 0; border-radius: 5px; padding: 8px 6px; text-align: start; color: #174e84; cursor: pointer; font: inherit; }
.lead-evidence button:hover { background: #fff; }
.lead-evidence code { font-size: 12px; font-weight: 700; }
.lead-evidence span { overflow-wrap: anywhere; }
.workspace-tabs button:focus-visible, .lead-evidence button:focus-visible { outline: 2px solid var(--lead-color, #14539a); outline-offset: 2px; }
@media(max-width:760px) {
  .report-lead.has-lead-evidence { grid-template-columns: minmax(0, 1fr); }
  .lead-evidence { border-inline-start: 0; border-top: 1px solid #ccd9e9; padding: 12px 0 0; }
}
.checked-paths { list-style: none; padding: 0; font-size: 13px; }
.checked-paths li { display: flex; flex-wrap: wrap; gap: 8px 20px; padding: 10px 0; border-bottom: 1px solid #edebe9; }
.checked-paths span { color: #605e5c; }
.report-lead h2 { font-size: clamp(24px, 2.4vw, 34px); line-height: 1.3; font-weight: 700; margin: 10px 0 12px; max-width: 900px; }
.failure-story { padding: 16px 0 22px; margin: 0; border-bottom: 1px solid var(--desk-line, #e8e7e5); }
.failure-story h3 { color: #605e5c; margin: 0; }
.failure-flow { display: flex; list-style: none; padding: 0; margin: 28px 0 0; }
.failure-flow li { flex: 1; min-width: 0; position: relative; padding: 0 32px; }
.failure-flow li:first-child { padding-left: 0; }.failure-flow li:last-child { padding-right: 0; }
.failure-flow button { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; width: 100%; border: 0; padding: 4px; margin: -4px; background: transparent; text-align: left; cursor: pointer; color: inherit; font: inherit; }
.flow-symbol { width: 48px; height: 48px; display: grid; place-items: center; border: 1px solid #e5b0b3; color: #a4262c; border-radius: 50%; background: #fff8f8; margin-bottom: 8px; transition: border-color 180ms, transform 180ms; }
.affected .flow-symbol { color: #9b6700; border-color: #e4d5ac; background: #fffdf6; }
.flow-object { font-size: 13px; color: #605e5c; }.failure-flow strong { font-size: 20px; line-height: 1.5; font-weight: 600; overflow-wrap: anywhere; }
.flow-source { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #0078d4; margin-top: 4px; }
.flow-arrow { position: absolute; right: -10px; top: 18px; color: #a19f9d; }
.failure-flow button:hover .flow-symbol { border-color: #0078d4; transform: translateY(-2px); }
.next-actions > h3 { display: flex; align-items: center; gap: 16px; font-size: 16px; }.next-actions > h3 > span { color: #73716e; font-size: 12px; font-weight: 400; }
.service-map { margin-bottom: 24px; padding: 18px; border: 1px solid var(--line); border-radius: var(--panel-radius); background: #fff; }
.map-heading { display: flex; flex-wrap: wrap; align-items: start; justify-content: space-between; gap: 8px 16px; }
.map-heading p, .map-evidence p { margin-top: 4px; font-size: 12px; color: var(--muted); }
.map-key { flex: none; color: var(--danger); background: #fff1ed; border-radius: 99px; padding: 3px 10px; font-size: 12px; }
.endpoint-comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
.endpoint-comparison button { --endpoint: #146747; --endpoint-bg: #eaf7f0; display: flex; align-items: center; gap: 10px; padding: 11px; text-align: left; border: 1px solid var(--line); border-radius: var(--control-radius); color: var(--endpoint); background: var(--endpoint-bg); }
.endpoint-comparison button.failed { --endpoint: #a12920; --endpoint-bg: #fff1ed; }
.endpoint-comparison button:hover { border-color: currentColor; }
.endpoint-icon { display: grid; place-items: center; width: 32px; height: 32px; border-radius: var(--control-radius); background: #fff; flex: none; }
.endpoint-port { display: grid; flex: 1; color: var(--text); font-size: 12px; }
.endpoint-port strong { font-size: 22px; line-height: 1.25; font-variant-numeric: tabular-nums; }
.endpoint-result { font-size: 12px; }
@media(max-width: 700px) { .endpoint-comparison { grid-template-columns: 1fr; } }
.map-evidence { padding-top: 12px; border-top: 1px solid var(--line); }
.map-evidence h4 { margin: 0; font-size: 13px; }
.map-observations { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.map-observations button { white-space: normal; justify-content: flex-start; text-align: left; border-radius: var(--control-radius); padding: 5px 9px; background: var(--surface); font-size: 12px; }
.map-observations button:hover { background: var(--accent-soft); }
.candidate-history { margin: 16px 0; }.candidate-history > summary { font-size: 13px; color: #73716e; padding: 8px 12px; cursor: pointer; }
.report-totals { display: flex; flex-wrap: wrap; gap: 8px 24px; font-size: 12px; color: #73716e; margin-top: 20px; }
.fact-strip { display: flex; margin: 28px 0 32px; border-top: 1px solid #e8e7e5; border-bottom: 1px solid #e8e7e5; }
.fact-strip button { flex: 1; min-width: 0; text-align: left; background: transparent; border: 0; border-right: 1px solid #e8e7e5; padding: 20px; font: inherit; cursor: pointer; position: relative; }
.fact-strip button:first-child { padding-left: 0; }.fact-strip button:last-child { border-right: 0; }
.fact-strip span { color: #73716e; font-size: 12px; display: block; margin-bottom: 8px; }
.fact-strip strong { display: block; font-size: 14px; font-weight: 600; padding-right: 12px; overflow-wrap: anywhere; }
.fact-strip svg { color: #0078d4; position: absolute; right: 12px; top: 20px; }
.split-wide { display: grid; grid-template-columns: minmax(0, 1fr) 256px; gap: 32px; }
.object-detail { padding-left: 24px; border-left: 1px solid #e8e7e5; }
.object-detail h3 span { font-size: 12px; color: #73716e; margin-left: 8px; }
.next-actions { margin-top: 32px; }.action-row { border-top: 1px solid #e8e7e5; }.action-row:last-child { border-bottom: 1px solid #e8e7e5; }
.action-row summary { display: flex; align-items: flex-start; gap: 16px; padding: 18px 0; cursor: pointer; list-style: none; line-height: 1.7; font-size: 13px; }.action-row summary > span:nth-child(2) { flex: 1; }.action-row summary svg { flex-shrink: 0; margin-top: 4px; }
.sequence { color: #0078d4; font-size: 12px; }.action-content { padding: 0 24px 20px 32px; }.action-content ul { font-size: 13px; padding-left: 18px; line-height: 1.8; }
.report-fold { border-bottom: 1px solid #e8e7e5; padding: 16px 0; margin-top: 8px; min-width: 0; }.report-fold summary { cursor: pointer; font-size: 13px; color: #605e5c; }.report-fold p, .report-fold ul, .report-fold ol { font-size: 13px; margin-top: 16px; line-height: 1.8; overflow-wrap: anywhere; }
.workspace-empty { min-height: 320px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 20px; color: #73716e; font-size: 14px; }
.replay-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 24px; }.replay-toolbar h3 { margin: 0 0 4px; }.replay-toolbar span { font-size: 12px; color: #73716e; }.replay-controls { display: flex; gap: 8px; }.replay-controls button { min-width: 36px; padding: 8px 12px; }
.process-split { display: grid; grid-template-columns: minmax(220px, 36%) minmax(0, 1fr); gap: 32px; }
.check-list { list-style: none; margin: 0; padding: 0; max-height: 570px; overflow-y: auto; border-right: 1px solid #e8e7e5; }
.check-list button { width: 100%; display: flex; gap: 12px; text-align: left; padding: 16px 12px; border: 0; border-left: 2px solid transparent; background: transparent; font: inherit; cursor: pointer; align-items: baseline; }
.check-list button.selected, .candidate-index button.selected, .evidence-index button.selected { background: #eff6fc; border-left-color: #0078d4; }
.check-number { font-size: 12px; color: #0078d4; }.check-copy { flex: 1; min-width: 0; }.check-copy strong { display: block; font-size: 13px; font-weight: 600; }.check-copy small { display: block; color: #73716e; font-size: 11px; margin-top: 6px; line-height: 1.6; overflow-wrap: anywhere; }.check-list time { font-size: 10px; color: #73716e; white-space: nowrap; }
.replay-scene { min-width: 0; }.current-observation { padding: 24px 0; border-top: 1px solid #e8e7e5; }.current-observation > span, .eyebrow { font-size: 12px; color: #73716e; }.current-observation h3 { font-size: 20px; margin: 12px 0; }.current-observation p { font-size: 14px; margin-bottom: 16px; }
.evidence-split, .cause-split { display: grid; grid-template-columns: minmax(220px, 30%) minmax(0, 1fr); gap: 32px; }
.evidence-index, .candidate-index { border-right: 1px solid #e8e7e5; padding-right: 16px; max-height: 720px; overflow-y: auto; }
.evidence-index h3 { font-size: 12px; margin: 20px 12px 8px; display: flex; gap: 12px; }.evidence-index h3 span { color: #8a8886; font-weight: 400; }.evidence-index section:first-child h3 { margin-top: 0; }
.evidence-index button, .candidate-index button { background: transparent; width: 100%; padding: 14px 12px; border: 0; border-left: 2px solid transparent; text-align: left; cursor: pointer; font: inherit; display: flex; gap: 8px; line-height: 1.6; }
.evidence-index strong { display: block; font-weight: 400; font-size: 12px; }.evidence-index small { display: block; font-size: 11px; color: #73716e; overflow-wrap: anywhere; margin-top: 6px; }.evidence-code { color: #0078d4; font-size: 11px; white-space: nowrap; }
.evidence-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }.evidence-heading h2 { font-size: 22px; }.observation-state { font-size: 12px; color: #605e5c; flex-shrink: 0; }.observation-state.abnormal { color: #a4262c; }.observation-state.unavailable, .observation-state.partial { color: #9b6700; }
.evidence-result { font-size: 14px; padding-bottom: 24px; border-bottom: 1px solid #e8e7e5; }
.resource-mapping dd { overflow-wrap: anywhere; min-width: 0; }
.resource-mapping .payload-table { grid-template-columns: minmax(130px, 1fr) minmax(0, 2fr); }
.event-chain { list-style: none; margin: 32px 0; padding: 0; }.event-chain li { display: grid; grid-template-columns: 80px minmax(0, 1fr); gap: 16px; position: relative; padding-bottom: 28px; }.event-chain time { font-size: 12px; color: #73716e; padding-top: 3px; }.event-chain li > div { border-left: 1px solid #d1d1ce; padding-left: 24px; position: relative; }.event-chain li > div::before { content: ''; position: absolute; left: -4px; top: 7px; width: 7px; height: 7px; border-radius: 50%; background: #0078d4; }.event-chain strong { font-weight: 600; font-size: 14px; }.event-chain p { font-size: 12px; color: #605e5c; margin-top: 8px; }.event-chain dl { display: grid; grid-template-columns: 36px minmax(0, 1fr); gap: 4px 12px; font-size: 11px; color: #73716e; margin-top: 12px; }.event-chain dd { margin: 0; overflow-wrap: anywhere; }
.payload-table { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: 16px; font-size: 13px; padding: 24px 0; }.payload-table dt { overflow-wrap: anywhere; }.payload-table dd { margin: 0; }.payload-table-wrap { overflow-x: auto; margin: 24px 0; }.payload-table-wrap table { width: 100%; font-size: 13px; border-collapse: collapse; }.payload-table-wrap td, .payload-table-wrap th { text-align: left; border-bottom: 1px solid #e8e7e5; padding: 12px; }
.source-button { margin-top: 24px; }.evidence-detail, .candidate-detail { min-width: 0; }
.event-identifiers { margin-top: 12px; font-size: 12px; color: #73716e; }.event-identifiers summary { cursor: pointer; }.event-identifiers dl { grid-template-columns: 60px minmax(0, 1fr); }
.candidate-index button { display: block; border-bottom: 1px solid #edebe9; padding: 16px 12px; }.candidate-meta { display: flex; justify-content: space-between; font-size: 11px; color: #73716e; gap: 12px; margin-bottom: 8px; }.candidate-meta .confirmed { color: #107c41; font-weight: 600; } .candidate-meta .excluded { color: var(--muted); }.candidate-index strong { font-size: 12px; font-weight: 400; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; overflow: hidden; overflow-wrap: anywhere; }
.candidate-detail h2 { font-size: 20px; }.candidate-graph { padding: 16px 0; margin: 16px 0; border-block: 1px solid #e8e7e5; }.relation-evidence { display: flex; flex-direction: column; gap: 20px; }.relation-node { border: 0; border-left: 2px dashed #a19f9d; padding: 8px 16px; background: transparent; text-align: left; font: inherit; cursor: pointer; position: relative; }.relation-node.support { border-left: 2px solid #107c41; }.relation-node.contradict { border-left: 2px solid #c42b1c; }.relation-node span { font-size: 11px; color: #73716e; }.relation-node strong { display: block; font-weight: 600; font-size: 13px; margin: 6px 0; overflow-wrap: anywhere; }.relation-node small { color: #73716e; font-size: 11px; overflow-wrap: anywhere; display: block; }.relation-empty { color: #73716e; font-size: 13px; }.relation-join { color: #a19f9d; text-align: center; }.hypothesis-node { display: flex; flex-direction: column; align-items: center; gap: 12px; }.hypothesis-node > span { font-size: 12px; color: #0078d4; }.hypothesis-node svg { color: #0078d4; }.hypothesis-node strong { font-size: 13px; font-weight: 600; color: #9b6700; }.candidate-gap { font-size: 13px; }.candidate-gap h3 { margin-bottom: 8px; }.evidence-chips { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; font-size: 12px; }.evidence-chips button { padding: 3px 8px; border: 0; background: #eff6fc; color: #0078d4; font-size: 11px; cursor: pointer; }
.check-copy strong, .evidence-index strong, .candidate-index strong { font-size: 14px; line-height: 1.7; }
.check-copy small, .evidence-index small, .relation-node small, .event-chain p { font-size: 13px; line-height: 1.7; }
.candidate-meta, .relation-node span { font-size: 12px; }
.candidate-index strong { display: block; overflow: visible; }
.candidate-gap p { font-size: 14px; }
.relation-node.citation { border-left: 2px solid #0078d4; }
.other-evidence .relation-evidence { margin-top: 20px; }
.hypothesis-node.confirmed strong, .hypothesis-node.confirmed svg, .hypothesis-node.supported strong { color: #107c41; }
button:hover { color: #0078d4; }button:focus-visible, summary:focus-visible { outline: 2px solid #0078d4; outline-offset: 2px; }
@media(max-width:1100px) { .split-wide { grid-template-columns: minmax(0, 1fr); }.object-detail { border-left: 0; padding-left: 0; border-top: 1px solid #e8e7e5; padding-top: 20px; }.process-split { grid-template-columns: minmax(200px, 40%) minmax(0, 1fr); gap: 20px; }.evidence-split, .cause-split { gap: 20px; } }
@media(max-width:760px) { .workspace-tabs { gap: 4px; }.workspace-tabs button { padding-inline: 8px; }.workspace-tabs button { font-size: 13px; }.workspace-panel { padding-top: 20px; }h2 { font-size: 20px; }.fact-strip { flex-direction: column; }.fact-strip button { border-right: 0; border-bottom: 1px solid #e8e7e5; padding: 16px 0; }.fact-strip button:last-child { border-bottom: 0; }.process-split, .evidence-split, .cause-split { grid-template-columns: minmax(0, 1fr); }.check-list { max-height: 260px; border-right: 0; border-bottom: 1px solid #e8e7e5; }.check-list time { display: block; }.evidence-index, .candidate-index { max-height: 260px; border-right: 0; padding-right: 0; border-bottom: 1px solid #e8e7e5; padding-bottom: 16px; }.evidence-heading { align-items: flex-start; flex-direction: column; gap: 0; }.event-chain li { grid-template-columns: 62px minmax(0, 1fr); gap: 8px; }.event-chain li > div { padding-left: 16px; }.replay-toolbar { align-items: flex-start; flex-wrap: wrap; }.replay-controls { margin-left: auto; } }
@media(prefers-reduced-motion:no-preference) { .workspace-panel { animation: reveal 180ms ease-out; } @keyframes reveal { from { opacity: .6; transform: translateY(3px); } to { opacity: 1; transform: none; } } }
@media(max-width:760px) { .report-lead h2 { font-size: 26px; }.failure-flow { flex-direction: column; gap: 32px; }.failure-flow li, .failure-flow li:first-child, .failure-flow li:last-child { padding: 0 0 0 64px; }.flow-symbol { position: absolute; left: 0; top: 4px; }.failure-flow strong { font-size: 18px; }.flow-arrow { right: auto; left: 14px; top: auto; bottom: -28px; transform: rotate(90deg); }.failure-story { padding: 24px 0; } }
@media(prefers-reduced-motion:reduce) { .flow-symbol { transition: none; }.failure-flow button:hover .flow-symbol { transform: none; } }
.findings-summary { margin: 24px 0; padding-top: 16px; border-top: 1px solid var(--line); }
.finding-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 32px; }
.finding-columns h4 { margin-top: 0; }
.finding-columns ul { padding-left: 20px; overflow-wrap: anywhere; }
.finding-columns li { margin-bottom: 8px; }
.finding-columns button { margin-inline-start: 8px; }
.current-observation { padding: 0 0 12px; border-top: 0; }
.check-list time { display: block; margin-top: 4px; }
.replay-controls { flex-wrap: wrap; }
.replay-controls [aria-pressed='true'] { border-color: var(--primary, #0078d4); }
.plan-list li { padding-block: 4px; }
.plan-list li span + span { margin-inline-start: 12px; }
.workspace-note { margin: 0 0 16px; color: var(--muted); }
.workspace-panel:focus-visible { outline-offset: 4px; }
.evidence-tools { margin-bottom: 16px; }
.evidence-tools > button { margin-bottom: 8px; }
.evidence-error { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; color: #a4262c; }
.evidence-sidebar { min-width: 0; }
.chart-filter { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; border-radius: 6px; background: var(--accent-soft); padding: 6px 8px; margin-bottom: 10px; font-size: 12px; overflow-wrap: anywhere; }
.evidence-sidebar .search-input { margin: 0 16px 12px 0; width: auto; }
.evidence-heading, .evidence-heading-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; }
.evidence-heading-actions .source-button { margin: 0; }
.payload-table dd, .evidence-detail, .candidate-detail, .candidate-index { min-width: 0; overflow-wrap: anywhere; }
.payload-table pre { margin: 0; max-height: 240px; overflow: auto; white-space: pre-wrap; }
@media(max-width:760px) { .finding-columns { grid-template-columns: minmax(0, 1fr); } }
.review-summary { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px 20px; margin-bottom: 14px; padding: 14px 16px; border: 1px solid var(--line); border-radius: var(--panel-radius); background: #fff; }
.review-summary p, .relation-note { margin-top: 4px; color: var(--muted); font-size: 12px; }
.review-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.review-pills > * { display: inline-flex; align-items: center; gap: 7px; padding: 5px 9px; border: 1px solid var(--line); border-radius: var(--control-radius); color: var(--text); background: var(--surface); font-size: 12px; }
.review-pills .abnormal { color: var(--danger); }
.review-pills button:hover, .review-pills button[aria-pressed="true"] { border-color: var(--blue); background: var(--accent-soft); }
.evidence-sidebar, .candidate-index, .evidence-detail, .candidate-detail { padding: 14px; border: 1px solid var(--line); border-radius: var(--panel-radius); background: #fff; align-self: start; }
.evidence-index { border: 0; padding: 0; }
.evidence-sidebar .search-input { max-width: none; margin: 0 0 14px; min-width: 0; }
.evidence-index button, .candidate-index button { border-radius: var(--control-radius); }
.evidence-code { align-self: start; padding: 2px 5px; border-radius: 5px; background: var(--surface); color: var(--blue); }
.evidence-code.abnormal, .observation-state.abnormal { background: #fff1ed; color: var(--danger); }
.evidence-heading > div { min-width: 0; }
.observation-state { padding: 4px 8px; border-radius: var(--control-radius); background: var(--surface); }
.evidence-result { margin: 14px 0; padding: 12px; border: 0; border-radius: var(--control-radius); background: var(--surface); overflow-wrap: anywhere; }
.candidate-detail > header { padding: 12px 14px; border-radius: var(--control-radius); background: var(--surface); }
.candidate-graph h3 .muted { font-size: 12px; font-weight: 400; }
.relation-evidence { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 206px), 1fr)); gap: 8px; margin-top: 12px; }
.relation-node { border: 1px solid var(--line); border-left: 2px dashed var(--muted); border-radius: var(--control-radius); background: var(--surface); }
.relation-node:hover { background: var(--accent-soft); }
.relation-node.citation span { color: var(--blue); }
.relation-node.support span { color: var(--success); }
.relation-node.contradict span { color: var(--danger); }
.candidate-gap { margin-top: 12px; padding: 12px; border-radius: var(--control-radius); background: #fff7e7; }
.candidate-gap p + p { margin-top: 8px; }
.visual-board, .timeline-board { min-width: 0; align-self: start; border: 1px solid var(--line); border-radius: var(--panel-radius); background: #fff; padding: 14px; }
.visual-heading { display: flex; align-items: start; gap: 9px; margin-bottom: 12px; color: var(--blue); }
.visual-heading h3 { color: var(--text); }
.visual-heading p { color: var(--muted); font-size: 12px; margin-top: 2px; }
.timeline-board .check-list { border: 0; }
.timeline-board .check-list li { position: relative; }
.timeline-board .check-list li:not(:last-child)::after { content: ""; position: absolute; top: 37px; bottom: -13px; left: 23px; border-left: 1px solid #b8cce2; pointer-events: none; }
.timeline-board .check-list button { position: relative; align-items: start; border-radius: var(--control-radius); padding: 10px 8px; }
.timeline-board .check-number { position: relative; z-index: 1; flex: none; display: grid; place-items: center; width: 27px; height: 27px; border: 1px solid #bbd2ed; border-radius: 50%; background: #fff; font-variant-numeric: tabular-nums; }
.timeline-board .selected .check-number { background: var(--blue); border-color: var(--blue); color: #fff; }
.timeline-board .check-number.abnormal { border-color: #e4a89f; color: var(--danger); }
.timeline-board .selected .check-number.abnormal { background: var(--danger); color: #fff; }
.replay-scene .observation-state { margin-inline-start: 8px; display: inline-block; }
.evidence-map section + section { margin-top: 14px; }
.evidence-map h3 { align-items: center; gap: 6px; padding: 0 0 6px; margin: 0; color: var(--text); overflow-wrap: anywhere; }
.evidence-map h3 span { margin-inline-start: auto; flex: none; }
.evidence-nodes { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 90px), 1fr)); gap: 6px; border-inline-start: 2px solid var(--line); padding-inline-start: 9px; }
.evidence-nodes button { display: grid; justify-items: start; gap: 3px; padding: 6px 8px; color: var(--muted); font-size: 11px; border: 1px solid var(--line); background: var(--surface); overflow-wrap: anywhere; }
.evidence-nodes button:hover, .evidence-nodes button.selected { background: var(--accent-soft); border-color: var(--blue); color: var(--text); }
.evidence-nodes button.abnormal:not(.selected) { border-inline-start-color: var(--danger); }
.evidence-nodes button.partial, .evidence-nodes button.unavailable { border-style: dashed; }
.evidence-detail { scroll-margin-top: 74px; }
.candidate-detail > .candidate-root { display: flex; align-items: start; gap: 9px; border: 1px solid #bfd3ec; background: var(--accent-soft); }
.candidate-root > svg { margin-top: 3px; color: var(--blue); }
.candidate-graph { margin-top: 0; padding-top: 0; border-top: 0; }
.relation-junction { display: grid; justify-items: center; color: var(--blue); }
.relation-junction::before { content: ""; height: 15px; border-inline-start: 1px solid #92accb; }
.relation-junction > span { display: flex; align-items: center; gap: 5px; border: 1px solid var(--line); border-radius: var(--control-radius); padding: 4px 8px; background: #fff; font-size: 12px; }
.candidate-graph .relation-note { text-align: center; }
.relation-map { padding: 10px; background: radial-gradient(#c8d6e7 1px, transparent 1px) 0 0 / 16px 16px; border: 1px solid var(--line); border-radius: var(--control-radius); }
.relation-map .relation-node { padding-inline-end: 24px; }
.relation-map .relation-node:not(:focus-visible)::after { content: ""; position: absolute; inset: 0 0 auto; height: 3px; border-radius: var(--control-radius) var(--control-radius) 0 0; background: #cad9ec; }
.relation-open { position: absolute; right: 6px; top: 9px; color: var(--blue); }
</style>
