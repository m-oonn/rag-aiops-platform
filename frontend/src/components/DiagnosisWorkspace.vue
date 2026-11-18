<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { clockTime, evidenceRows, fieldLabel, logEvents, questionText, readableText, reportActions, reportFacts, reportOverview, serviceLabel, topology, visualCandidates } from "../lib/diagnosisVisuals";
import DiagnosisTopology from "./DiagnosisTopology.vue";
import KnowledgeReferences from "./KnowledgeReferences.vue";
import Markdown from "./Markdown.vue";
import Icon from "./Icon.vue";
import { readWorkspace, writeWorkspace } from "../lib/history";
import { session } from "../lib/session";
const props = defineProps({
  runId: String, report: String, diagnosis: Object, investigation: Object,
  evidence: { type: Array, default: () => [] }, hypotheses: { type: Array, default: () => [] },
  plans: { type: Array, default: () => [] }, status: String, statusText: String, usage: Object,
  knowledgeReferences: { type: Array, default: () => [] },
});
defineEmits(["evidence"]);
const tab = ref("report"), selectedNode = ref(""), selectedId = ref(""), selectedCandidateId = ref("");
const cursor = ref(0), playing = ref(false);
const followStatus = ref(true), restoreCursorId = ref("");
let timer;
const records = computed(() => evidenceRows(props.evidence, props.investigation));
const graph = computed(() => topology(records.value, props.diagnosis?.asset_registration || { allowed_services: [] }));
const candidates = computed(() => visualCandidates(props.investigation, props.diagnosis, props.hypotheses));
const facts = computed(() => reportFacts(props.diagnosis, records.value));
const healthyChecks = computed(() => props.diagnosis?.kind === 'healthy_within_scope'
  ? records.value.filter(row => ['services', 'ports', 'dependency_probe'].includes(row.kind)) : []);
const actions = computed(() => reportActions(props.diagnosis));
const overview = computed(() => reportOverview(props.diagnosis, records.value));
const currentCandidates = computed(() => candidates.value.filter(row => row.status !== "dropped"));
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
  { id: "report", name: "诊断报告" }, { id: "process", name: "排查过程", count: records.value.length },
  { id: "evidence", name: "现场证据", count: records.value.length }, { id: "causes", name: "候选原因", count: candidates.value.length },
]);
const conclusionLabel = computed(() => ({
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
  graph.value.nodes.find((node) => node.id === facts.value[0]?.object) || graph.value.nodes[0]);
const selectedRecord = computed(() => selectedId.value ? records.value.find((row) => row.id === selectedId.value) : records.value[0]);
const selectedCandidate = computed(() => candidates.value.find((row) => row.id === selectedCandidateId.value) ||
  candidates.value.find((row) => props.diagnosis?.kind === "confirmed_cause" && row.id === props.diagnosis.hypothesis_id) ||
  candidates.value.find((row) => row.id === props.investigation?.leading_id) || candidates.value[0]);
const groups = computed(() => graph.value.nodes.filter((node) => node.evidence.length));
const candidateLinks = computed(() => (selectedCandidate.value?.relations || []).map((link) => ({ ...link, record: records.value.find((row) => row.id === link.id) })));
const mainCandidateLinks = computed(() => selectedCandidate.value?.status === "confirmed" && overview.value.steps.length
  ? overview.value.steps.map(step => candidateLinks.value.find(link => link.id === step.id)).filter(Boolean) : candidateLinks.value);
const otherCandidateLinks = computed(() => candidateLinks.value.filter(link => !mainCandidateLinks.value.includes(link)));
const relationLabel = (value) => ({ citation: "结论依据", support: "支持", contradict: "反驳", neutral: "关联记录 · 关系未定" }[value] || "关系未定");
const questions = computed(() => (props.diagnosis?.unresolved_questions || []).map(question => {
  const text = typeof question === "string" ? question : question.question;
  const alternative = props.diagnosis?.alternatives?.find(item => item.explanation === text);
  return { id: question?.id, text: questionText(question),
    reason: alternative?.critical === false ? alternative.noncritical_reason : "" };
}));
const selectedEvents = computed(() => logEvents(selectedRecord.value?.payload));
function selectTab(value) { followStatus.value = false; tab.value = value; }
function openEvidence(id) { selectedId.value = id; selectTab("evidence"); }
function selectCandidate(id) { followStatus.value = false; selectedCandidateId.value = id; }
function selectNode(id) { followStatus.value = false; selectedNode.value = id; }
function pause() { clearInterval(timer); timer = undefined; playing.value = false; }
function seek(index) { pause(); restoreCursorId.value = ""; followStatus.value = false; cursor.value = Math.max(0, Math.min(records.value.length - 1, index)); }
function selectReplayNode(name) {
  selectNode(name);
  const id = replayGraph.value.nodes.find(node => node.id === name)?.evidence.at(-1)?.id;
  if (id) seek(records.value.findIndex(row => row.id === id));
}
function play() {
  if (playing.value) return pause();
  if (records.value.length < 2) return;
  restoreCursorId.value = ""; followStatus.value = false;
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
  pause(); cursor.value = 0;
  const saved = readWorkspace(session.user?.id, props.runId);
  const text = key => typeof saved?.[key] === "string" ? saved[key] : "";
  selectedId.value = text("evidenceId"); selectedNode.value = text("nodeId"); selectedCandidateId.value = text("candidateId");
  restoreCursorId.value = text("cursorId"); followStatus.value = saved?.followStatus !== false;
  tab.value = saved?.tab || (props.status === "running" ? "process" : "report");
  const index = records.value.findIndex(row => row.id === restoreCursorId.value);
  if (index >= 0) { cursor.value = index; restoreCursorId.value = ""; }
}, { immediate: true });
watch(() => props.status, (value) => {
  if (!followStatus.value) return;
  if (value === "completed" || value === "pending_review") tab.value = "report";
  if (value === "running") tab.value = "process";
});
watch(() => records.value.map(row => row.id).join("|"), () => {
  const index = records.value.findIndex(row => row.id === restoreCursorId.value);
  if (index >= 0) { cursor.value = index; restoreCursorId.value = ""; }
  if (cursor.value >= records.value.length) { pause(); cursor.value = Math.max(0, records.value.length - 1); }
});
watch([tab, selectedId, selectedNode, selectedCandidateId, cursor, followStatus], () => {
  writeWorkspace(session.user?.id, props.runId, { tab: tab.value, evidenceId: selectedId.value, nodeId: selectedNode.value,
    candidateId: selectedCandidateId.value, cursorId: restoreCursorId.value || current.value?.id || "", followStatus: followStatus.value });
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
    <section :id="`diagnosis-panel-${tab}`" role="tabpanel" :aria-labelledby="`diagnosis-tab-${tab}`" class="workspace-panel">
      <template v-if="tab === 'report'">
        <template v-if="diagnosis || report">
          <header class="report-lead">
            <span :class="['conclusion-label', { confirmed: diagnosis?.kind === 'confirmed_cause' }]">{{ conclusionLabel }}</span>
            <h2>{{ overview.title }}</h2>
            <p v-if="records.length" class="report-scope">{{ clockTime(records.at(-1).time) }} 的现场结果<span> · {{ records.length }} 项证据</span><span v-if="usage?.elapsed_s != null"> · 用时 {{ Math.round(usage.elapsed_s) }} 秒</span></p>
          </header>
          <section v-if="graph.nodes.length" class="service-map" aria-label="故障位置与登记依赖"><h3>故障位置与依赖关系</h3><p>节点显示本轮实际观测；连线表示登记关系，不能单独证明故障传播。</p><DiagnosisTopology :graph="graph" :selected="activeNode?.id" @select="selectedNode = $event" @evidence="openEvidence" /><div v-if="activeNode" class="map-evidence"><h3>{{ serviceLabel(activeNode.id) }}</h3><button v-for="row in activeNode.evidence" :key="row.id" class="observation-link" @click="openEvidence(row.id)"><span>{{ row.label }} · {{ row.title }}</span><strong>{{ row.result }}</strong></button></div></section>
          <h3>已查清的事</h3><p v-if="!facts.length">{{ diagnosis?.kind === 'healthy_within_scope' ? '本次已检查的对象和时间内未发现异常，不能代表所有功能长期正常。' : '当前证据尚未形成可确认的故障事实。' }}</p>
          <ul v-if="healthyChecks.length" class="checked-paths" aria-label="本次实际检查"><li v-for="row in healthyChecks" :key="row.id"><button class="text-button" @click="openEvidence(row.id)">{{ row.label }} · {{ row.title }}</button><span>{{ row.result }}</span></li></ul>
          <section v-if="overview.steps.length" class="failure-story" aria-label="故障影响过程">
            <h3>故障怎么影响用户</h3>
            <ol class="failure-flow"><li v-for="(step, index) in overview.steps" :key="step.id" :class="step.tone">
              <button @click="openEvidence(step.id)" :aria-label="`${step.object}：${step.title}，查看证据`">
                <span class="flow-symbol"><Icon :name="step.icon" :size="24" /></span>
                <span class="flow-object">{{ step.object }}</span><strong>{{ step.title }}</strong>
                <span class="flow-source">{{ records.find(row => row.id === step.id)?.label }} · 现场记录<Icon name="arrow" :size="14" /></span>
              </button><Icon v-if="index < overview.steps.length - 1" class="flow-arrow" name="arrow" :size="22" />
            </li></ol>
          </section>
          <div v-else-if="facts.length" class="fact-strip" aria-label="已发现的异常">
            <button v-for="fact in facts" :key="fact.id" @click="openEvidence(fact.id)"><span>{{ serviceLabel(fact.object) }}</span><strong>{{ fact.text }}</strong><Icon name="arrow" :size="16" /></button>
          </div>
          <section class="findings-summary"><h3>已排除的事项</h3><ul v-if="candidates.some(row => row.status === 'excluded')"><li v-for="candidate in candidates.filter(row => row.status === 'excluded')" :key="candidate.id">{{ candidate.text }}<button v-for="id in candidate.evidence.slice(0, 1)" :key="id" class="text-button" @click="openEvidence(id)">查看依据</button></li></ul><p v-else>尚无满足证据标准的排除结论。</p><h3>尚未查清的事</h3><ul v-if="questions.length"><li v-for="(question, index) in questions" :key="question.id || index">{{ question.text }}<details v-if="question.reason" class="question-boundary"><summary>对当前结论的影响（模型判断）</summary><p>以下理由仍未独立核验：{{ readableText(question.reason) }}</p></details></li></ul><p v-else>未覆盖的业务路径、时间及历史原因仍不能确定。</p><details v-if="diagnosis?.limitations?.length" class="evidence-limits"><summary>证据范围与校验限制（{{ diagnosis.limitations.length }} 项）</summary><p>以下限制影响结论范围，不能据此推断未测业务正常。</p><ul><li v-for="text in diagnosis.limitations" :key="text">{{ readableText(text) }}</li></ul></details></section>
          <div v-if="actions.length" class="next-actions"><h3>接下来怎么做<span>尚未执行</span></h3>
            <details v-for="(action, index) in actions" :key="JSON.stringify([action.action, action.scope])" class="action-row">
              <summary><span class="sequence">{{ String(index + 1).padStart(2, '0') }}</span><span>{{ actionTitle(action) }}</span><Icon name="down" :size="16" /></summary>
              <div class="action-content"><p v-if="actionTitle(action) !== action.action">{{ action.action }}</p><template v-for="section in [{ title: '操作前确认', rows: action.preconditions }, { title: '操作影响', rows: action.risks }, { title: '恢复后检查', rows: action.verification }]" :key="section.title">
                <template v-if="section.rows.length"><h4>{{ section.title }}</h4><ul><li v-for="text in section.rows" :key="text">{{ text }}</li></ul></template>
              </template><div class="evidence-chips"><button v-for="id in action.evidence" :key="id" @click="openEvidence(id)">{{ records.find(row => row.id === id)?.label || '查看依据' }}</button></div></div>
            </details>
          </div>
          <div v-else-if="diagnosis?.kind === 'healthy_within_scope'" class="next-actions"><h3>接下来怎么做</h3><p>本次已检查路径未发现故障。若再次出现异常，请记录发生时间、网址和具体操作，再检查对应失败路径；未覆盖功能仍需分别验证。</p></div>
          <KnowledgeReferences v-if="knowledgeReferences.length" :references="knowledgeReferences" />
          <details v-if="report || diagnosis" class="report-fold"><summary>完整报告与技术详情</summary><p>以下保留模型原始叙述，其中自由文本的因果解释未经逐句核验；确认等级及证据边界见上方结论。</p><p v-if="diagnosis?.scope">{{ diagnosis.scope }}</p><Markdown v-if="report" :content="report" @evidence="openEvidence" /><p v-else>{{ diagnosis?.conclusion }}</p></details>
        </template>
        <div v-else class="workspace-empty"><Icon name="pulse" :size="36" /><span>{{ statusText || '描述故障现象，开始排查' }}</span></div>
      </template>
      <template v-if="tab === 'process'">
        <div class="replay-toolbar"><div><h3>采集回放</h3><span v-if="records.length">{{ cursor + 1 }} / {{ records.length }} 项现场记录</span></div>
          <div class="replay-controls"><button class="button" :disabled="!records.length || cursor === 0" @click="seek(cursor - 1)" aria-label="上一项"><Icon name="arrowLeft" :size="16" /></button>
            <button class="button" :disabled="records.length < 2" :aria-pressed="playing" @click="play">{{ playing ? '暂停' : cursor === records.length - 1 && records.length ? '重新回放' : '回放' }}</button>
            <button class="button" :disabled="!records.length || cursor === records.length - 1" @click="seek(cursor + 1)" aria-label="下一项"><Icon name="arrow" :size="16" /></button></div>
        </div>
        <div v-if="records.length" class="process-split">
          <ol class="check-list" aria-label="实际采集顺序"><li v-for="(row, index) in records" :key="row.id"><button :class="{ selected: cursor === index }" :aria-current="cursor === index ? 'step' : undefined" @click="seek(index)">
            <span class="check-number">{{ String(index + 1).padStart(2, '0') }}</span><span class="check-copy"><strong>{{ row.title }}</strong><small>{{ row.result }}</small></span><time>{{ clockTime(row.time) }}</time>
          </button></li></ol>
          <div class="replay-scene"><DiagnosisTopology :graph="replayGraph" :current="current?.id" :selected="selectedNode" @select="selectReplayNode" @evidence="openEvidence" />
            <div v-if="current" class="current-observation" aria-live="polite"><span>{{ current.label }} · {{ clockTime(current.time) }}</span><h3>{{ current.title }}</h3><p>{{ current.result }}</p><button class="text-button" @click="openEvidence(current.id)">查看证据<Icon name="arrow" :size="16" /></button></div>
          </div>
        </div>
        <div v-else class="workspace-empty">{{ status === 'running' ? statusText || '正在获取现场观测' : '暂无现场采集记录' }}</div>
        <details v-if="plans.length" class="report-fold"><summary>排查计划 · {{ plans.length }}</summary><ol><li v-for="(plan, index) in plans" :key="index">{{ plan.text }}</li></ol></details>
        <details v-if="diagnosis?.stop_reason || investigation?.stop_reason" class="report-fold"><summary>排查结束记录</summary><p>{{ diagnosis?.stop_reason || investigation?.stop_reason }}</p></details>
      </template>
      <template v-if="tab === 'evidence'">
        <div v-if="!records.length" class="workspace-empty">尚无现场证据</div>
        <div v-else class="evidence-split"><nav class="evidence-index" aria-label="按对象选择证据"><section v-for="group in groups" :key="group.id"><h3>{{ serviceLabel(group.id) }}<span>{{ group.evidence.length }}</span></h3>
          <button v-for="row in group.evidence" :key="row.id" :aria-pressed="selectedRecord?.id === row.id" :class="{ selected: selectedRecord?.id === row.id }" @click="selectedId = row.id"><span class="evidence-code">{{ row.label }}</span><span><strong>{{ row.title }}</strong><small>{{ row.result }}</small></span></button>
        </section></nav>
          <article v-if="selectedRecord" class="evidence-detail"><header class="evidence-heading"><div><span class="eyebrow">{{ selectedRecord.label }} · {{ clockTime(selectedRecord.time) }}</span><h2>{{ selectedRecord.title }}</h2></div><span :class="['observation-state', selectedRecord.state]">{{ selectedRecord.stateLabel }}</span></header>
            <p class="evidence-result">{{ selectedRecord.result }}</p>
            <ol v-if="selectedEvents.length" class="event-chain"><li v-for="event in selectedEvents" :key="event.index"><time>{{ clockTime(event.time) }}</time><div><strong>{{ event.label }}</strong><p v-if="event.text">{{ event.text }}</p><details v-if="event.data" class="event-identifiers"><summary>定位信息</summary><dl><template v-for="field in ['pid', 'request_id', 'instance_id']" :key="field"><template v-if="event.data[field] != null"><dt>{{ {pid:'进程号',request_id:'请求编号',instance_id:'实例编号'}[field] }}</dt><dd>{{ event.data[field] }}</dd></template></template></dl></details></div></li></ol>
            <dl v-else-if="selectedRecord.kind === 'configuration' && selectedRecord.payload" class="payload-table"><template v-for="(value, key) in selectedRecord.payload.values || {}" :key="key"><dt>{{ fieldLabel(key) }}</dt><dd>{{ value }}</dd></template></dl>
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
            <button class="button source-button" @click="$emit('evidence', selectedRecord.id)">来源与原文<Icon name="arrow" :size="16" /></button>
          </article>
          <p v-else role="alert">该引用的现场证据尚未读取或已不可用，请重新载入证据台账后核对。</p>
        </div>
      </template>
      <template v-if="tab === 'causes'">
        <div v-if="!candidates.length" class="workspace-empty">暂无候选原因</div>
        <div v-else class="cause-split"><nav class="candidate-index" aria-label="选择候选原因"><button v-for="candidate in currentCandidates" :key="candidate.id" :class="{ selected: selectedCandidate?.id === candidate.id }" :aria-pressed="selectedCandidate?.id === candidate.id" @click="selectedCandidateId = candidate.id">
          <span class="candidate-meta">{{ candidate.number }} · {{ candidate.type }}<span :class="{ excluded: candidate.status === 'excluded' }">{{ candidate.statusLabel }}</span></span><strong>{{ candidate.text }}</strong>
        </button><details v-if="pastCandidates.length" class="candidate-history"><summary>此前排查 · {{ pastCandidates.length }}</summary><button v-for="candidate in pastCandidates" :key="candidate.id" :class="{ selected: selectedCandidate?.id === candidate.id }" :aria-pressed="selectedCandidate?.id === candidate.id" @click="selectedCandidateId = candidate.id"><span class="candidate-meta">{{ candidate.number }}<span>{{ candidate.statusLabel }}</span></span><strong>{{ candidate.text }}</strong></button></details></nav>
          <article v-if="selectedCandidate" class="candidate-detail"><header><span class="eyebrow">{{ selectedCandidate.number }} · {{ selectedCandidate.type }}</span><h2>{{ selectedCandidate.text }}</h2><span :class="['conclusion-label', { confirmed: ['confirmed', 'supported'].includes(selectedCandidate.status) }]">{{ selectedCandidate.statusLabel }}</span></header>
            <div class="candidate-graph" aria-label="证据与候选关系"><div class="relation-evidence"><button v-for="link in mainCandidateLinks" :key="link.id" :class="['relation-node', link.relation]" @click="openEvidence(link.id)"><span>{{ link.record?.label || '证据' }} · {{ relationLabel(link.relation) }}</span><strong>{{ link.record?.title || link.id }}</strong><small v-if="link.record">{{ link.record.result }}</small></button><p v-if="!candidateLinks.length" class="relation-empty">尚无绑定证据</p></div><span class="relation-join" aria-hidden="true">→</span><div :class="['hypothesis-node', selectedCandidate.status]"><span>{{ selectedCandidate.number }}</span><Icon :name="selectedCandidate.status === 'confirmed' ? 'check' : 'search'" :size="28" /><strong>{{ selectedCandidate.statusLabel }}</strong></div></div>
            <details v-if="otherCandidateLinks.length" class="report-fold other-evidence"><summary>其他依据 · {{ otherCandidateLinks.length }}</summary><div class="relation-evidence"><button v-for="link in otherCandidateLinks" :key="link.id" :class="['relation-node', link.relation]" @click="openEvidence(link.id)"><span>{{ link.record?.label || '证据' }} · {{ relationLabel(link.relation) }}</span><strong>{{ link.record?.title || '现场记录' }}</strong><small v-if="link.record">{{ link.record.result }}</small></button></div></details>
            <div v-if="!['confirmed', 'supported', 'excluded', 'dropped'].includes(selectedCandidate.status) && (selectedCandidate.question || selectedCandidate.nextCheck)" class="candidate-gap"><h3>待核实</h3><p>{{ selectedCandidate.question || selectedCandidate.nextCheck }}</p></div>
            <details v-if="selectedCandidate.limitation" class="report-fold"><summary>判断依据与保留项</summary><p>{{ selectedCandidate.limitation }}</p></details>
            <details v-if="selectedCandidate.original && selectedCandidate.original !== selectedCandidate.text" class="report-fold"><summary>候选原始描述</summary><p>{{ selectedCandidate.original }}</p></details>
          </article>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.diagnostic-workspace { min-width: 0; color: #323130; }
.workspace-tabs { display: flex; gap: 28px; border-bottom: 1px solid #e8e7e5; overflow-x: auto; }
.workspace-tabs button { display: flex; gap: 8px; align-items: center; border: 0; border-bottom: 2px solid transparent; background: transparent; padding: 16px 0; font: inherit; color: #605e5c; cursor: pointer; white-space: nowrap; }
.workspace-tabs button.active { color: #0078d4; border-color: #0078d4; font-weight: 600; }
.workspace-tabs span { color: #73716e; font-size: 12px; font-weight: 400; }
.workspace-panel { padding-top: 28px; }
h2 { font-size: 24px; line-height: 1.5; font-weight: 600; margin: 12px 0; overflow-wrap: anywhere; }
h3 { margin: 0 0 16px; font-size: 14px; font-weight: 600; }
h4 { font-size: 13px; margin: 16px 0 8px; }
p { line-height: 1.7; overflow-wrap: anywhere; }
.conclusion-label { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: #9b6700; }
.conclusion-label::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: #bf8b00; }
.conclusion-label.confirmed { color: #107c41; }.conclusion-label.confirmed::before { background: #107c41; }
.report-scope { color: #73716e; font-size: 12px; margin: 12px 0; }
.checked-paths { list-style: none; padding: 0; font-size: 13px; }
.checked-paths li { display: flex; flex-wrap: wrap; gap: 8px 20px; padding: 10px 0; border-bottom: 1px solid #edebe9; }
.checked-paths span { color: #605e5c; }
.report-lead h2 { font-size: 32px; line-height: 1.4; margin: 12px 0 16px; max-width: 900px; }
.failure-story { padding: 32px 0; margin: 24px 0 0; border-top: 1px solid #e8e7e5; border-bottom: 1px solid #e8e7e5; }
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
.map-evidence { padding: 20px 0 0; border-top: 1px solid #e8e7e5; }
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
.observation-link { width: 100%; text-align: left; border: 0; border-bottom: 1px solid #edebe9; padding: 12px 0; background: transparent; font: inherit; cursor: pointer; }
.observation-link span { font-size: 11px; color: #73716e; display: block; }.observation-link strong { font-size: 12px; font-weight: 400; display: block; margin-top: 6px; overflow-wrap: anywhere; }
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
.payload-table { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; font-size: 13px; padding: 24px 0; }.payload-table dt { overflow-wrap: anywhere; }.payload-table dd { margin: 0; }.payload-table-wrap { overflow-x: auto; margin: 24px 0; }.payload-table-wrap table { width: 100%; font-size: 13px; border-collapse: collapse; }.payload-table-wrap td, .payload-table-wrap th { text-align: left; border-bottom: 1px solid #e8e7e5; padding: 12px; }
.source-button { margin-top: 24px; }.evidence-detail, .candidate-detail { min-width: 0; }
.event-identifiers { margin-top: 12px; font-size: 12px; color: #73716e; }.event-identifiers summary { cursor: pointer; }.event-identifiers dl { grid-template-columns: 60px minmax(0, 1fr); }
.candidate-index button { display: block; border-bottom: 1px solid #edebe9; padding: 16px 12px; }.candidate-meta { display: flex; justify-content: space-between; font-size: 11px; color: #73716e; gap: 12px; margin-bottom: 8px; }.candidate-meta .excluded { color: #107c41; }.candidate-index strong { font-size: 12px; font-weight: 400; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; overflow: hidden; overflow-wrap: anywhere; }
.candidate-detail h2 { font-size: 20px; }.candidate-graph { display: grid; grid-template-columns: minmax(0, 1fr) 40px 100px; gap: 8px; align-items: center; padding: 32px 0; margin: 24px 0; border-top: 1px solid #e8e7e5; border-bottom: 1px solid #e8e7e5; }.relation-evidence { display: flex; flex-direction: column; gap: 20px; }.relation-node { border: 0; border-left: 2px dashed #a19f9d; padding: 8px 16px; background: transparent; text-align: left; font: inherit; cursor: pointer; position: relative; }.relation-node.support { border-left: 2px solid #107c41; }.relation-node.contradict { border-left: 2px solid #c42b1c; }.relation-node span { font-size: 11px; color: #73716e; }.relation-node strong { display: block; font-weight: 600; font-size: 13px; margin: 6px 0; overflow-wrap: anywhere; }.relation-node small { color: #73716e; font-size: 11px; overflow-wrap: anywhere; display: block; }.relation-empty { color: #73716e; font-size: 13px; }.relation-join { color: #a19f9d; text-align: center; }.hypothesis-node { display: flex; flex-direction: column; align-items: center; gap: 12px; }.hypothesis-node > span { font-size: 12px; color: #0078d4; }.hypothesis-node svg { color: #0078d4; }.hypothesis-node strong { font-size: 13px; font-weight: 600; color: #9b6700; }.candidate-gap { font-size: 13px; }.candidate-gap h3 { margin-bottom: 8px; }.evidence-chips { display: flex; gap: 8px; margin-top: 12px; }.evidence-chips button { padding: 3px 8px; border: 0; background: #eff6fc; color: #0078d4; font-size: 11px; cursor: pointer; }
.check-copy strong, .evidence-index strong, .candidate-index strong { font-size: 14px; line-height: 1.7; }
.check-copy small, .evidence-index small, .relation-node small, .event-chain p { font-size: 13px; line-height: 1.7; }
.candidate-meta, .relation-node span { font-size: 12px; }
.candidate-index strong { display: block; overflow: visible; }
.candidate-gap p { font-size: 14px; }
.relation-node.citation { border-left: 2px solid #0078d4; }
.other-evidence .relation-evidence { margin-top: 20px; }
.hypothesis-node.confirmed strong, .hypothesis-node.confirmed svg, .hypothesis-node.supported strong { color: #107c41; }
button:hover { color: #0078d4; }button:focus-visible, summary:focus-visible { outline: 2px solid #0078d4; outline-offset: 2px; }
@media(max-width:1100px) { .split-wide { grid-template-columns: minmax(0, 1fr); }.object-detail { border-left: 0; padding-left: 0; border-top: 1px solid #e8e7e5; padding-top: 20px; }.process-split { grid-template-columns: minmax(200px, 40%) minmax(0, 1fr); gap: 20px; }.check-list time { display: none; }.evidence-split, .cause-split { gap: 20px; } }
@media(max-width:760px) { .workspace-tabs { gap: 20px; }.workspace-tabs button { font-size: 13px; }.workspace-panel { padding-top: 20px; }h2 { font-size: 20px; }.fact-strip { flex-direction: column; }.fact-strip button { border-right: 0; border-bottom: 1px solid #e8e7e5; padding: 16px 0; }.fact-strip button:last-child { border-bottom: 0; }.process-split, .evidence-split, .cause-split { grid-template-columns: minmax(0, 1fr); }.check-list { max-height: 260px; border-right: 0; border-bottom: 1px solid #e8e7e5; }.check-list time { display: block; }.evidence-index, .candidate-index { max-height: 260px; border-right: 0; padding-right: 0; border-bottom: 1px solid #e8e7e5; padding-bottom: 16px; }.evidence-heading { align-items: flex-start; flex-direction: column; gap: 0; }.event-chain li { grid-template-columns: 62px minmax(0, 1fr); gap: 8px; }.event-chain li > div { padding-left: 16px; }.candidate-graph { grid-template-columns: minmax(0, 1fr) 16px 76px; gap: 4px; }.replay-toolbar { align-items: flex-start; flex-wrap: wrap; }.replay-controls { margin-left: auto; } }
@media(prefers-reduced-motion:no-preference) { .workspace-panel { animation: reveal 180ms ease-out; } @keyframes reveal { from { opacity: .6; transform: translateY(3px); } to { opacity: 1; transform: none; } } }
@media(max-width:760px) { .report-lead h2 { font-size: 26px; }.failure-flow { flex-direction: column; gap: 32px; }.failure-flow li, .failure-flow li:first-child, .failure-flow li:last-child { padding: 0 0 0 64px; }.flow-symbol { position: absolute; left: 0; top: 4px; }.failure-flow strong { font-size: 18px; }.flow-arrow { right: auto; left: 14px; top: auto; bottom: -28px; transform: rotate(90deg); }.failure-story { padding: 24px 0; } }
@media(prefers-reduced-motion:reduce) { .flow-symbol { transition: none; }.failure-flow button:hover .flow-symbol { transform: none; } }
</style>
