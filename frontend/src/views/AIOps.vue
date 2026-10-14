<template>
  <div class="aiops-container">
    <div class="header-row">
      <h2>AIOps 运维诊断</h2>
      <el-tag type="info" effect="plain">计划-执行-重规划 Agent</el-tag>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <el-input
        v-model="query"
        type="textarea"
        :rows="2"
        placeholder="描述故障现象，或粘贴网址检查网站，例如：订单服务 5xx 突增，帮我定位原因"
        :disabled="running"
        @keyup.enter.ctrl="runDiagnose"
      />
      <div class="input-actions">
        <div class="examples">
          <el-button
            v-for="ex in examples"
            :key="ex"
            size="small"
            text
            bg
            :disabled="running"
            @click="query = ex"
          >{{ ex }}</el-button>
        </div>
        <div class="main-actions">
          <el-button
            v-if="running"
            type="warning"
            @click="cancelDiagnose"
          >取消诊断</el-button>
          <el-button
            v-else
            type="primary"
            :disabled="!query.trim()"
            @click="runDiagnose"
          >开始诊断</el-button>
          <el-button
            v-if="report || steps.length"
            type="info"
            plain
            size="default"
            @click="clearAll"
          >清空</el-button>
        </div>
      </div>
    </div>

    <!-- 状态行 -->
    <el-alert
      v-if="statusText"
      :title="statusText"
      :type="errorMsg ? 'error' : (running ? 'info' : 'success')"
      :closable="false"
      show-icon
      class="status-alert"
    />

    <!-- 诊断过程 timeline -->
    <el-card v-if="steps.length" shadow="never" class="section-card">
      <template #header>诊断计划 ({{ doneCount }}/{{ steps.length }})</template>
      <el-timeline>
        <el-timeline-item
          v-for="(step, idx) in steps"
          :key="idx"
          :type="step.done ? 'success' : (idx === doneCount && running ? 'primary' : 'info')"
          :hollow="!step.done"
          :timestamp="step.done ? '已完成' : (idx === doneCount && running ? '执行中' : '待执行')"
        >
          <div class="step-line">
            <el-tag
              v-if="step.parallel"
              size="small"
              type="info"
              effect="plain"
              class="step-tag"
            >并行采集</el-tag>
            <span>{{ step.text }}</span>
          </div>
        </el-timeline-item>
      </el-timeline>
    </el-card>

    <!-- 最终报告 -->
    <el-card v-if="report" shadow="never" class="section-card report-card">
      <template #header>
        <div class="report-header">
          <span><el-icon><Document /></el-icon> 诊断报告</span>
          <el-button size="small" text type="primary" @click="copyReport">
            复制报告
          </el-button>
        </div>
      </template>
      <div class="report-body" v-html="renderedReport"></div>
    </el-card>

    <!-- 证据来源：诚实标记本次哪些证据源可用/缺席 -->
    <el-card v-if="evidenceSources.length" shadow="never" class="section-card">
      <template #header>
        <span><el-icon><DataLine /></el-icon> 证据来源</span>
      </template>
      <div class="tag-row">
        <el-tag
          v-for="src in evidenceSources"
          :key="src.source"
          :type="src.available ? 'success' : 'danger'"
          effect="plain"
        >{{ src.label }}：{{ src.available ? '可用' : '缺席' }}</el-tag>
      </div>
      <el-alert
        v-if="missingSources.length"
        class="meta-hint"
        type="warning"
        :closable="false"
        show-icon
        :title="`本次缺失证据源：${missingSources.join('、')}。相关结论按“未取得真实数据”处理，请勿当作确定根因。`"
      />
    </el-card>

    <!-- 假设空间：按概率降序 -->
    <el-card v-if="sortedHypotheses.length" shadow="never" class="section-card">
      <template #header>
        <span><el-icon><Histogram /></el-icon> 假设空间（候选根因概率）</span>
      </template>
      <div v-for="h in sortedHypotheses" :key="h.id" class="hypo-row">
        <div class="hypo-head">
          <span class="hypo-name">{{ h.name }}</span>
          <span class="hypo-prob">{{ pct(h.probability) }}</span>
        </div>
        <el-progress
          :percentage="Math.round((h.probability || 0) * 100)"
          :show-text="false"
          :stroke-width="8"
        />
      </div>
    </el-card>

    <!-- 旁开支线：矛盾触发的并行验证 -->
    <el-card v-if="sidebarBranches.length" shadow="never" class="section-card">
      <template #header>
        <span><el-icon><Connection /></el-icon> 旁开支线（矛盾触发的并行验证）</span>
      </template>
      <el-timeline>
        <el-timeline-item
          v-for="(b, i) in sidebarBranches"
          :key="i"
          :type="b.status === 'done' ? 'success' : 'primary'"
          :hollow="b.status !== 'done'"
        >
          <div class="branch-line">
            <el-tag size="small" type="warning" effect="plain">{{ b.status || 'running' }}</el-tag>
            <span>{{ b.target_hypothesis_name || hypothesisName(b.target_hypothesis_id) }}</span>
          </div>
          <div v-if="b.trigger_reason" class="branch-reason">触发原因：{{ b.trigger_reason }}</div>
        </el-timeline-item>
      </el-timeline>
    </el-card>

    <!-- 信念演进：各轮假设概率变化 -->
    <el-card v-if="beliefHistory.length > 1 && beliefColumns.length" shadow="never" class="section-card">
      <template #header>
        <span><el-icon><TrendCharts /></el-icon> 信念演进（各轮假设概率）</span>
      </template>
      <div class="belief-scroll">
        <el-table :data="beliefHistory" size="small" border>
          <el-table-column prop="step" label="轮次" width="70" />
          <el-table-column
            v-for="col in beliefColumns"
            :key="col.id"
            :label="col.name"
            min-width="110"
          >
            <template #default="{ row }">
              {{ pct(row.probabilities && row.probabilities[col.id]) }}
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <el-empty v-if="!steps.length && !running && !report" description="输入故障现象，开始诊断" />
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, DataLine, Histogram, Connection, TrendCharts } from '@element-plus/icons-vue'
import { streamSSE } from '../utils/sse'
import { getAiopsStreamUrl, renderMarkdown } from '../utils/chat'

const query = ref('')
const sessionId = ref('web-' + Math.random().toString(36).slice(2, 10))
const running = ref(false)
const steps = ref([])        // [{ text, done, parallel }]
const report = ref('')
const statusText = ref('')
const errorMsg = ref('')
// 诊断元数据（complete 事件下发）：让"后端算了的"可见，避免静默丢弃
const hypotheses = ref([])        // 假设空间快照 [{ id, name, probability, ... }]
const sidebarBranches = ref([])   // 旁开支线 [{ target_hypothesis_name, status, trigger_reason }]
const beliefHistory = ref([])     // 信念演进 [{ step, probabilities: { id: prob } }]
const evidenceSources = ref([])   // 证据源可用性 [{ source, label, available, tools }]
let abortController = null

const examples = [
  '检查网站 https://www.baidu.com 是否正常',
  '订单服务 5xx 突增，排查根因',
  '数据同步服务 CPU 飙升，定位原因',
]

const doneCount = computed(() => steps.value.filter((s) => s.done).length)

// 报告渲染：复用全局 Markdown 管线（marked + DOMPurify，支持 GFM 表格），
// 并先剥离后端嵌入的 diagnostic_meta 注释（程序用元数据，不给人看）。
const renderedReport = computed(() => {
  const text = (report.value || '').replace(/<!--[\s\S]*?-->/g, '')
  return renderMarkdown(text)
})

// ── 诊断元数据的展示派生量 ──
const sortedHypotheses = computed(() =>
  [...hypotheses.value].sort((a, b) => (b.probability || 0) - (a.probability || 0))
)
const missingSources = computed(() =>
  evidenceSources.value.filter((s) => !s.available).map((s) => s.label)
)
const beliefColumns = computed(() =>
  hypotheses.value.map((h) => ({ id: h.id, name: h.name }))
)
const hypothesisName = (id) => {
  const h = hypotheses.value.find((x) => x.id === id)
  return h ? h.name : id
}
const pct = (p) => `${Math.round((p || 0) * 100)}%`

const resetState = () => {
  steps.value = []
  report.value = ''
  statusText.value = ''
  errorMsg.value = ''
  hypotheses.value = []
  sidebarBranches.value = []
  beliefHistory.value = []
  evidenceSources.value = []
}

const clearAll = () => {
  query.value = ''
  resetState()
}

const cancelDiagnose = () => {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  running.value = false
  statusText.value = '诊断已取消'
}

const copyReport = async () => {
  try {
    await navigator.clipboard.writeText(report.value)
    ElMessage.success('报告已复制到剪贴板')
  } catch (e) {
    ElMessage.error('复制失败，请手动复制')
  }
}

// 按 type 分发单条 SSE 事件到本地状态
const handleEvent = (evt) => {
  switch (evt.type) {
    case 'plan':
      steps.value = (evt.plan || []).map((raw) => {
        const text = String(raw || '')
        // [并行] 是执行器的并行批调度标记，不属于展示文案：剥离并转成小标签
        const parallel = text.trim().startsWith('[并行]')
        return {
          text: parallel ? text.trim().slice(4).trim() : text,
          parallel,
          done: false,
        }
      })
      statusText.value = evt.message || '诊断计划已制定'
      break
    case 'step_complete': {
      const next = steps.value.find((s) => !s.done)
      if (next) next.done = true
      statusText.value = evt.message || `步骤完成 (${doneCount.value}/${steps.value.length})`
      break
    }
    case 'status':
      statusText.value = evt.message || '诊断中...'
      break
    case 'report':
      report.value = evt.report || ''
      statusText.value = evt.message || '诊断报告已生成'
      break
    case 'complete':
      if (!report.value && evt.response) report.value = evt.response
      // 诊断元数据：后端已下发，前端照单展示（假设空间/旁开支线/信念演进/证据源可用性）
      hypotheses.value = evt.hypothesis_space || []
      sidebarBranches.value = evt.sidebar_branches || []
      beliefHistory.value = evt.belief_history || []
      evidenceSources.value = evt.evidence_source_availability || []
      statusText.value = evt.message || '诊断完成'
      break
    case 'error':
      errorMsg.value = evt.message || '诊断出错'
      statusText.value = evt.message || '诊断出错'
      ElMessage.error(errorMsg.value)
      break
    default:
      break
  }
}

const runDiagnose = async () => {
  if (!query.value.trim() || running.value) return
  if (abortController) {
    abortController.abort()
  }
  abortController = new AbortController()
  resetState()
  running.value = true
  statusText.value = '正在连接诊断服务...'

  try {
    await streamSSE(
      getAiopsStreamUrl(),
      { query: query.value, session_id: sessionId.value },
      {
        signal: abortController.signal,
        onEvent: handleEvent,
        showMessage: (msg) => ElMessage.error(msg),
      }
    )
  } catch (e) {
    if (e.name === 'AbortError') {
      statusText.value = '诊断已取消'
      return
    }
    errorMsg.value = e.message || '诊断请求异常'
    statusText.value = errorMsg.value
    ElMessage.error(errorMsg.value)
  } finally {
    running.value = false
    abortController = null
  }
}

onUnmounted(() => {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
})
</script>

<style scoped>
.aiops-container {
  max-width: 900px;
  margin: 0 auto;
}
.header-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.input-area {
  margin-bottom: 16px;
}
.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
}
.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.main-actions {
  display: flex;
  gap: 8px;
}
.status-alert {
  margin-bottom: 16px;
}
.section-card {
  margin-bottom: 16px;
}
.report-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.step-line {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  line-height: 1.6;
}
.step-tag {
  flex-shrink: 0;
}
.report-body {
  line-height: 1.7;
  color: #303133;
  word-break: break-word;
}
.report-body :deep(h1),
.report-body :deep(h2) {
  font-size: 18px;
  margin: 16px 0 8px;
}
.report-body :deep(h1:first-child) {
  margin-top: 0;
}
.report-body :deep(h3) {
  font-size: 16px;
  margin: 14px 0 6px;
}
.report-body :deep(h4) {
  font-size: 15px;
  margin: 12px 0 6px;
}
.report-body :deep(p) {
  margin: 8px 0;
}
.report-body :deep(ul),
.report-body :deep(ol) {
  margin: 8px 0;
  padding-left: 22px;
}
.report-body :deep(li) {
  margin: 4px 0;
}
.report-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
  font-size: 14px;
}
.report-body :deep(th),
.report-body :deep(td) {
  border: 1px solid #e4e7ed;
  padding: 8px 12px;
  text-align: left;
  vertical-align: top;
}
.report-body :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
  white-space: nowrap;
}
.report-body :deep(blockquote) {
  margin: 10px 0;
  padding: 8px 12px;
  border-left: 3px solid #c0c4cc;
  background: #fafafa;
  color: #606266;
}
.report-body :deep(code) {
  background: #f5f7fa;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: Consolas, Monaco, monospace;
}
.report-body :deep(pre) {
  background: #f5f7fa;
  padding: 10px 12px;
  border-radius: 6px;
  overflow-x: auto;
}
.report-body :deep(hr) {
  border: none;
  border-top: 1px solid #ebeef5;
  margin: 14px 0;
}
.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.meta-hint {
  margin-top: 12px;
}
.hypo-row {
  margin-bottom: 14px;
}
.hypo-row:last-child {
  margin-bottom: 0;
}
.hypo-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
  font-size: 14px;
}
.hypo-name {
  color: #303133;
}
.hypo-prob {
  color: #909399;
  font-variant-numeric: tabular-nums;
}
.branch-line {
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.6;
}
.branch-reason {
  margin-top: 4px;
  color: #909399;
  font-size: 13px;
}
.belief-scroll {
  overflow-x: auto;
}
</style>
