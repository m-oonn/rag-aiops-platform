<template>
  <div class="aiops-container">
    <div class="header-row">
      <div class="header-title">
        <h2>智能诊断</h2>
        <p class="header-sub">描述故障现象，Agent 自动制定计划、采集证据并定位原因</p>
      </div>
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
      <div class="examples">
        <span class="examples-label">试一试</span>
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
      <div class="input-actions">
        <el-switch
          v-model="terminalEnabled"
          inline-prompt
          active-text="终端诊断"
          inactive-text="常规诊断"
          :disabled="running || Boolean(pendingApproval)"
          class="terminal-switch"
        />
        <div class="main-actions">
          <el-button
            v-if="running"
            type="warning"
            @click="cancelDiagnose"
          >取消诊断</el-button>
          <el-button
            v-else-if="pendingApproval"
            type="primary"
            @click="continueDiagnose"
          >继续诊断</el-button>
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
            :disabled="running || Boolean(pendingApproval)"
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

    <el-card v-if="pendingApproval" shadow="never" class="section-card approval-card">
      <template #header>终端命令待审批</template>
      <div class="approval-command"><code>{{ pendingApproval.command }}</code></div>
      <div class="approval-meta">
        <span>审批期限：{{ approvalExpiry }}</span>
        <span>审批身份：Termcp local</span>
      </div>
      <el-link :href="termcpUiUrl" target="_blank" type="primary">打开 Termcp 审批页面</el-link>
    </el-card>

    <!-- 诊断过程 timeline -->
    <el-card v-if="steps.length" shadow="never" class="section-card">
      <template #header>诊断计划 ({{ doneCount }}/{{ steps.length }})</template>
      <el-timeline>
        <el-timeline-item
          v-for="(step, idx) in steps"
          :key="idx"
          :id="'step-' + idx"
          :type="step.done ? 'success' : (idx === doneCount && running ? 'primary' : 'info')"
          :hollow="!step.done"
          :timestamp="step.done ? '已完成' : (idx === doneCount && running ? '执行中' : '待执行')"
        >
          <div class="step-line" :class="{ 'step-active': idx === doneCount && running }">
            <el-icon v-if="step.done" class="step-check"><CircleCheckFilled /></el-icon>
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
    <el-card v-if="report" id="report-card" shadow="never" class="section-card report-card">
      <template #header>
        <div class="report-header">
          <span><el-icon><Document /></el-icon> 诊断报告</span>
          <el-button size="small" text type="primary" @click="copyReport">
            复制报告
          </el-button>
        </div>
      </template>
      <div v-if="diagnosis" class="diagnosis-result">
        <div class="diagnosis-banner">
          <div class="diagnosis-banner-main">
            <el-tag :type="kindTagType" effect="dark" round size="large">
              {{ diagnosisLabels[diagnosis.kind] || '未知结论类型' }}
            </el-tag>
            <span class="diagnosis-conclusion">{{ diagnosis.conclusion }}</span>
          </div>
          <div class="diagnosis-banner-meta">
            已检查范围：{{ diagnosis.scope || '未记录' }} · 目标：{{ diagnosis.target_id || '未记录' }}
          </div>
          <div v-if="diagnosis.stop_reason" class="diagnosis-banner-meta">
            停止原因：{{ diagnosis.stop_reason }}
          </div>
        </div>

        <div class="diagnosis-sections">
          <section v-if="(diagnosis.observed_findings || []).length" class="diagnosis-section">
            <h4 class="diagnosis-section-title"><el-icon><DataLine /></el-icon> 现场观察</h4>
            <ul class="diagnosis-list">
              <li v-for="(item, index) in diagnosis.observed_findings || []" :key="`finding-${index}`" class="diagnosis-item">
                <span>已观察到：{{ item.summary }}</span>
                <span class="diagnosis-item-meta">{{ item.collected_at || '采集时间未知' }}</span>
                <el-button
                  v-if="item.evidence_id"
                  text size="small" type="primary"
                  class="diagnosis-ref"
                  @click="focusEvidence(item.evidence_id)"
                >{{ item.evidence_id }}</el-button>
              </li>
            </ul>
          </section>

          <section v-if="(diagnosis.alternatives || []).length" class="diagnosis-section">
            <h4 class="diagnosis-section-title"><el-icon><Connection /></el-icon> 替代解释核查</h4>
            <ul class="diagnosis-list">
              <li v-for="(item, index) in diagnosis.alternatives || []" :key="index" class="diagnosis-item">
                <el-tag
                  size="small"
                  effect="plain"
                  :type="item.status === 'excluded' && item.verification === 'predicate_verified' ? 'success' : (item.status === 'supported' ? 'primary' : 'info')"
                >{{ item.status === 'excluded' && item.verification === 'predicate_verified' ? '已核查解释' : item.status === 'supported' ? '现场支持的条件' : '未决解释' }}</el-tag>
                <span>{{ item.explanation }}</span>
                <span v-if="item.limitation" class="diagnosis-item-meta">{{ item.limitation }}</span>
              </li>
            </ul>
          </section>

          <section v-if="(diagnosis.unresolved_questions || []).length" class="diagnosis-section">
            <h4 class="diagnosis-section-title"><el-icon><QuestionFilled /></el-icon> 未决问题</h4>
            <ul class="diagnosis-list">
              <li v-for="(item, index) in diagnosis.unresolved_questions || []" :key="`question-${index}`" class="diagnosis-item">
                <span>未决问题：{{ item.question }}</span>
                <span v-if="item.limitation" class="diagnosis-item-meta">{{ item.limitation }}</span>
              </li>
            </ul>
          </section>

          <section
            v-if="(diagnosis.limitations || []).length || (diagnosis.contradictions || []).length"
            class="diagnosis-section"
          >
            <h4 class="diagnosis-section-title"><el-icon><WarningFilled /></el-icon> 限制与矛盾</h4>
            <ul class="diagnosis-list">
              <li
                v-for="(item, index) in [...(diagnosis.limitations || []), ...(diagnosis.contradictions || [])]"
                :key="index"
                class="diagnosis-item"
              >
                <span>限制/矛盾：{{ item }}</span>
              </li>
            </ul>
          </section>

          <section v-if="(diagnosis.validation_issues || []).length" class="diagnosis-section">
            <h4 class="diagnosis-section-title"><el-icon><WarningFilled /></el-icon> 判断校验</h4>
            <ul class="diagnosis-list">
              <li v-for="(item, index) in diagnosis.validation_issues || []" :key="`issue-${index}`" class="diagnosis-item">
                <span>判断校验：{{ item }}</span>
              </li>
            </ul>
          </section>
        </div>

        <div v-if="(diagnosis.evidence || []).length" class="diagnosis-citations">
          <el-button
            v-for="(ref, index) in diagnosis.evidence || []"
            :key="index"
            text size="small" type="primary"
            @click="focusEvidence(ref.evidence_id)"
          >{{ ref.evidence_id }}：{{ ref.quote }}</el-button>
        </div>
      </div>
      <el-tag v-else type="info">历史格式：未记录结构化结论级别</el-tag>
      <div class="report-body" v-html="renderedReport"></div>
    </el-card>

    <!-- 假设空间：按概率降序 -->
    <el-card v-if="sortedHypotheses.length" shadow="never" class="section-card">
      <template #header>
        <span><el-icon><Histogram /></el-icon> 假设空间（候选根因概率）</span>
      </template>
      <div v-for="(h, i) in sortedHypotheses" :key="h.id" class="hypo-row">
        <div class="hypo-head">
          <span class="hypo-name">
            <span class="hypo-rank" :class="{ top: i === 0 }">{{ i + 1 }}</span>{{ h.name }}
          </span>
          <span class="hypo-prob" :class="{ top: i === 0 }">{{ pct(h.probability) }}</span>
        </div>
        <el-progress
          :percentage="Math.round((h.probability || 0) * 100)"
          :show-text="false"
          :stroke-width="8"
          :color="hypoColor(i)"
        />
      </div>
    </el-card>

    <!-- 信念演进：各轮假设概率变化 -->
    <el-card v-if="beliefHistory.length > 1" shadow="never" class="section-card">
      <template #header>
        <span><el-icon><TrendCharts /></el-icon> 信念演进（各轮假设概率）</span>
      </template>
      <div ref="beliefChartRef" class="belief-chart"></div>
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

    <!-- 证据来源：诚实标记本次哪些证据源可用/缺席 -->
    <el-card v-if="evidenceSources.length" shadow="never" class="section-card">
      <template #header>
        <span><el-icon><DataLine /></el-icon> 证据来源</span>
      </template>
      <div class="tag-row">
        <el-tag
          v-for="src in evidenceSources"
          :key="src.source"
          :type="sourceTagType(src)"
          effect="plain"
        >{{ src.label }}：{{ sourceLabels[src.status] || (src.available ? '已注册（未核验）' : '缺席') }}{{ src.checked_at ? ' · ' + src.checked_at : '' }}</el-tag>
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

    <el-card v-if="evidenceTimeline.length" shadow="never" class="section-card">
      <template #header>
        <span><el-icon><DataLine /></el-icon> 证据时间线</span>
        <el-button v-if="currentThreadId" text size="small" @click="loadEvidence(currentThreadId)">刷新证据状态</el-button>
      </template>
      <div v-for="(target, id) in targetStatuses" :key="id" class="evidence-meta">
        目标 {{ id }}：{{ target.status === 'online' ? '在线' : target.status === 'offline' ? '离线' : target.status === 'stale' ? '状态过期' : '状态不可用' }}
        · 最近连接消息：{{ target.last_seen || '未知' }}
      </div>
      <el-collapse class="evidence-collapse">
        <el-collapse-item name="records" :title="`采集记录（${evidenceTimeline.length}）`">
          <el-timeline>
            <el-timeline-item
              v-for="item in evidenceTimeline"
              :key="item.evidence_id"
              :id="'evidence-' + item.evidence_id"
              :type="item.fresh ? 'success' : 'warning'"
              :timestamp="item.collected_at || '采集时间未知'"
            >
              <div><el-tag size="small" effect="plain">{{ item.target_id }}</el-tag> {{ item.kind }}</div>
              <div class="evidence-meta">来源：{{ item.source }} · {{ item.fresh ? '新鲜' : '过期/不可用' }}</div>
              <div class="evidence-summary">{{ item.summary }}</div>
              <el-button v-if="canReadRaw && item.raw_available" text size="small" @click="loadRawEvidence(item)">查看现场证据（脱敏）</el-button>
              <pre v-if="rawEvidence[item.evidence_id]" class="evidence-raw">{{ rawEvidence[item.evidence_id] }}</pre>
            </el-timeline-item>
          </el-timeline>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- 空状态 -->
    <div v-if="!steps.length && !running && !report" class="empty-state">
      <el-icon :size="42" class="empty-icon"><Search /></el-icon>
      <p class="empty-title">输入故障现象，开始诊断</p>
      <div class="empty-examples">
        <button
          type="button"
          class="example-card"
          v-for="ex in examples"
          :key="ex"
          :disabled="running"
          @click="query = ex"
        >
          <el-icon><Search /></el-icon>
          <span>{{ ex }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onUnmounted, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Document, DataLine, Histogram, Connection, TrendCharts,
  CircleCheckFilled, QuestionFilled, WarningFilled, Search,
} from '@element-plus/icons-vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { streamSSE } from '../utils/sse'
import { getAiopsStreamUrl, getAiopsRunUrl, renderMarkdown } from '../utils/chat'
import { extractToolText } from '../utils/reportText'
import { getAuthHeaders, handleAuthError } from '../utils/auth'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const query = ref('')
const sessionId = ref('web-' + Math.random().toString(36).slice(2, 10))
const running = ref(false)
const terminalEnabled = ref(false)
const pendingApproval = ref(null)
const termcpUiUrl = ref('http://127.0.0.1:18765')
const steps = ref([])        // [{ text, done, parallel }]
const report = ref('')
const diagnosis = ref(null)
const diagnosisLabels = { confirmed_cause: '原因已确认', localized_fault: '故障层已定位，深层原因未明', healthy_within_scope: '检查范围内未见异常', unlocated: '尚未定位' }
const sourceLabels = { registered: '已注册（未核验）', callable: '实际调用成功', offline: '目标离线', authentication_failed: '认证失败', permission_denied: '权限不足', stale: '数据陈旧', unavailable: '不可用' }
const focusEvidence = async (id) => {
  const element = document.getElementById('evidence-' + id)
  if (element) element.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  else ElMessage.info('该历史引用无法映射到当前证据账本，不能回读')
}
const statusText = ref('')
const errorMsg = ref('')
// 诊断元数据（complete 事件下发）：让"后端算了的"可见，避免静默丢弃
const hypotheses = ref([])        // 假设空间快照 [{ id, name, probability, ... }]
const sidebarBranches = ref([])   // 旁开支线 [{ target_hypothesis_name, status, trigger_reason }]
const beliefHistory = ref([])     // 信念演进 [{ step, probabilities: { id: prob } }]
const evidenceSources = ref([])   // 证据源可用性 [{ source, label, available, tools }]
const evidenceTimeline = ref([])  // Windows Probe/其他现场证据事件
const currentThreadId = ref('')
const targetStatuses = ref({})
const canReadRaw = ref(false)
const rawEvidence = ref({})
let abortController = null

const examples = [
  '检查网站 https://www.baidu.com 是否正常',
  '订单服务 5xx 突增，排查根因',
  '数据同步服务 CPU 飙升，定位原因',
]

const doneCount = computed(() => steps.value.filter((s) => s.done).length)

// 报告渲染：复用全局 Markdown 管线（marked + DOMPurify，支持 GFM 表格），
// 先剥离后端嵌入的 diagnostic_meta 注释（程序用元数据，不给人看），
// 再把直出的工具原始返回（[{"type":"text",...}]）提取成可读文本。
const renderedReport = computed(() => {
  const text = (report.value || '').replace(/<!--[\s\S]*?-->/g, '')
  return renderMarkdown(extractToolText(text))
})

// ── 诊断元数据的展示派生量 ──
const sortedHypotheses = computed(() =>
  [...hypotheses.value].sort((a, b) => (b.probability || 0) - (a.probability || 0))
)
const missingSources = computed(() =>
  evidenceSources.value.filter((s) => !s.available).map((s) => s.label)
)
const hypothesisName = (id) => {
  const h = hypotheses.value.find((x) => x.id === id)
  return h ? h.name : id
}
const pct = (p) => `${Math.round((p || 0) * 100)}%`
const approvalExpiry = computed(() => {
  const ts = Number(pendingApproval.value?.expires_at || 0)
  return ts ? new Date(ts).toLocaleString() : '无有效期限'
})

// 结构化结论的展示形态
const kindTagType = computed(() => ({
  confirmed_cause: 'success',
  localized_fault: 'primary',
  healthy_within_scope: 'info',
  unlocated: 'warning',
}[diagnosis.value?.kind] || 'info'))
const sourceTagType = (src) => {
  if (src.status === 'callable') return 'success'
  if (!src.available) return 'danger'
  if (['offline', 'authentication_failed', 'permission_denied', 'stale', 'unavailable'].includes(src.status)) return 'danger'
  return 'info'
}
const hypoColor = (rank) => (rank === 0 ? '#2b7de9' : '#a0cfff')

// ── 信念演进折线图（echarts 按需引入，仅折线模块） ──
const beliefChartRef = ref(null)
let beliefChart = null
const renderBeliefChart = () => {
  if (!beliefHistory.value.length) return
  nextTick(() => {
    try {
      if (!beliefChartRef.value) return
      if (!beliefChart) beliefChart = echarts.init(beliefChartRef.value)
      const first = beliefHistory.value[0]?.probabilities || {}
      const ids = hypotheses.value.length
        ? hypotheses.value.map((h) => h.id)
        : Object.keys(first)
      const palette = ['#2b7de9', '#27a35d', '#e08a1e', '#7b57d9', '#e05c5c', '#12b3a8']
      beliefChart.setOption({
        color: palette,
        tooltip: { trigger: 'axis', valueFormatter: (v) => `${v}%` },
        legend: { top: 0, type: 'scroll', icon: 'roundRect', itemWidth: 12, itemHeight: 6 },
        grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
        xAxis: {
          type: 'category',
          boundaryGap: true,
          data: beliefHistory.value.map((b) => `第 ${b.step} 轮`),
        },
        yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
        series: ids.map((id, i) => ({
          name: hypothesisName(id),
          type: 'line',
          smooth: true,
          symbolSize: 6,
          data: beliefHistory.value.map((b) => Math.round((b.probabilities?.[id] || 0) * 100)),
          zIndex: hypotheses.value.length ? (i === 0 ? 3 : 2) : 2,
        })),
      }, true)
      beliefChart.resize()
    } catch (_) {
      // 图表渲染是纯展示增强，失败不影响诊断数据展示
    }
  })
}
watch([beliefHistory, hypotheses], renderBeliefChart, { deep: true })
const onChartResize = () => { try { beliefChart?.resize() } catch (_) { /* noop */ } }

// 运行中跟随当前执行步骤；报告生成后滚到报告卡
watch(doneCount, async (n) => {
  if (!running.value || !steps.value.length) return
  await nextTick()
  const idx = Math.min(n, steps.value.length - 1)
  document.getElementById('step-' + idx)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
})

const loadEvidence = async (threadId) => {
  currentThreadId.value = threadId
  try {
    const response = await fetch(`${getAiopsRunUrl(threadId)}/evidence`, {
      headers: getAuthHeaders(),
    })
    if (!response.ok) {
      handleAuthError(response.status, { showMessage: (msg) => ElMessage.error(msg) })
      return
    }
    const payload = await response.json()
    if (currentThreadId.value !== threadId) return
    canReadRaw.value = Boolean(payload.can_read_raw)
    const persisted = (payload.evidence || []).map((item) => ({
      ...item,
      summary: item.summary || '',
      fresh: Boolean(item.fresh),
    }))
    const merged = new Map(evidenceTimeline.value.map((item) => [item.evidence_id, item]))
    persisted.forEach((item) => merged.set(item.evidence_id, item))
    evidenceTimeline.value = [...merged.values()]
    await Promise.all([...new Set(persisted.map((item) => item.target_id))].map(async (targetId) => {
      try {
        const res = await fetch(`/api/v1/aiops/targets/${encodeURIComponent(targetId)}/status`, { headers: getAuthHeaders() })
        const target = res.ok ? await res.json() : { status: 'unavailable' }
        if (currentThreadId.value === threadId) targetStatuses.value[targetId] = target
      } catch (_) {
        if (currentThreadId.value === threadId) targetStatuses.value[targetId] = { status: 'unavailable' }
      }
    }))
  } catch (_) {
    // Evidence display is best-effort and must not change the diagnosis result.
  }
}

const loadRawEvidence = async (item) => {
  const threadId = currentThreadId.value
  try {
    const res = await fetch(`${getAiopsRunUrl(threadId)}/evidence/${encodeURIComponent(item.evidence_id)}`, { headers: getAuthHeaders() })
    if (!res.ok) throw new Error('无法读取现场证据')
    const data = await res.json()
    if (currentThreadId.value === threadId) rawEvidence.value[item.evidence_id] = JSON.stringify(data.raw ?? '原始内容不可用', null, 2)
  } catch (_) {
    ElMessage.error('无法读取现场证据')
  }
}

const resetState = () => {
  steps.value = []
  report.value = ''
  diagnosis.value = null
  statusText.value = ''
  errorMsg.value = ''
  hypotheses.value = []
  sidebarBranches.value = []
  beliefHistory.value = []
  evidenceSources.value = []
  evidenceTimeline.value = []
  currentThreadId.value = ''
  targetStatuses.value = {}
  canReadRaw.value = false
  rawEvidence.value = {}
  pendingApproval.value = null
}

const clearAll = () => {
  query.value = ''
  resetState()
  localStorage.removeItem('aiops_last_thread')
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
      diagnosis.value = evt.diagnosis || diagnosis.value
      report.value = evt.report || ''
      statusText.value = evt.message || '诊断报告已生成'
      break
    case 'complete':
      diagnosis.value = evt.diagnosis || diagnosis.value
      pendingApproval.value = null
      localStorage.removeItem('aiops_pending_thread')
      if (!report.value && evt.response) report.value = evt.response
      // 诊断元数据：后端已下发，前端照单展示（假设空间/旁开支线/信念演进/证据源可用性）
      hypotheses.value = evt.hypothesis_space || []
      sidebarBranches.value = evt.sidebar_branches || []
      beliefHistory.value = evt.belief_history || []
      evidenceSources.value = evt.evidence_source_availability || []
      if (evt.thread_id) {
        localStorage.setItem('aiops_last_thread', evt.thread_id)
        loadEvidence(evt.thread_id)
      }
      statusText.value = evt.message || '诊断完成'
      nextTick(() => {
        document.getElementById('report-card')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
      })
      break
    case 'evidence':
      evidenceTimeline.value.push(evt)
      statusText.value = `已采集现场证据：${evt.kind || 'unknown'}`
      break
    case 'error':
      if (pendingApproval.value && !['resume_conflict', 'terminal_approval_invalid'].includes(evt.stage)) {
        pendingApproval.value = null
        localStorage.removeItem('aiops_pending_thread')
      }
      errorMsg.value = evt.message || '诊断出错'
      statusText.value = evt.message || '诊断出错'
      ElMessage.error(errorMsg.value)
      break
    case 'pending_terminal_approval':
      pendingApproval.value = evt
      termcpUiUrl.value = evt.termcp_ui_url || termcpUiUrl.value
      localStorage.setItem('aiops_pending_thread', evt.thread_id)
      statusText.value = evt.message || '终端命令等待审批'
      break
    default:
      break
  }
}

const runDiagnose = async () => {
  if (!query.value.trim() || running.value || pendingApproval.value) return
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
      { query: query.value, session_id: sessionId.value, terminal_enabled: terminalEnabled.value },
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

const continueDiagnose = async () => {
  const threadId = pendingApproval.value?.thread_id
  if (!threadId || running.value) return
  abortController = new AbortController()
  running.value = true
  statusText.value = '正在核验 Termcp 审批状态...'
  errorMsg.value = ''
  try {
    await streamSSE(`${getAiopsRunUrl(threadId)}/continue`, {}, {
      signal: abortController.signal,
      onEvent: handleEvent,
      showMessage: (msg) => ElMessage.error(msg),
    })
    if (!pendingApproval.value) localStorage.removeItem('aiops_pending_thread')
  } catch (e) {
    if (e.name === 'AbortError') return
    errorMsg.value = e.message || '恢复诊断失败'
    statusText.value = errorMsg.value
    ElMessage.error(errorMsg.value)
    await restorePendingRun()
  } finally {
    running.value = false
    abortController = null
  }
}

const restorePendingRun = async () => {
  const threadId = localStorage.getItem('aiops_pending_thread') || localStorage.getItem('aiops_last_thread')
  if (!threadId) return
  try {
    const response = await fetch(getAiopsRunUrl(threadId), { headers: getAuthHeaders() })
    if (!response.ok) {
      handleAuthError(response.status, { showMessage: (msg) => ElMessage.error(msg) })
      if (response.status === 404) {
        pendingApproval.value = null
        localStorage.removeItem('aiops_pending_thread')
        localStorage.removeItem('aiops_last_thread')
      }
      return
    }
    const run = await response.json()
    await loadEvidence(threadId)
    if (run.status === 'pending_terminal' && run.terminal_approval) {
      pendingApproval.value = { ...run.terminal_approval, thread_id: run.thread_id }
      termcpUiUrl.value = run.termcp_ui_url || termcpUiUrl.value
      statusText.value = '终端命令等待 Termcp UI 审批'
    } else {
      pendingApproval.value = null
      localStorage.removeItem('aiops_pending_thread')
      if (run.report) report.value = run.report
      diagnosis.value = run.diagnosis || null
    }
  } catch (_) {
    statusText.value = '无法恢复待审批诊断状态'
  }
}

onMounted(() => {
  window.addEventListener('resize', onChartResize)
  restorePendingRun()
})

onUnmounted(() => {
  window.removeEventListener('resize', onChartResize)
  try { beliefChart?.dispose() } catch (_) { /* noop */ }
  beliefChart = null
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
  margin-bottom: 16px;
}
.header-title h2 {
  margin: 0 0 4px;
}
.header-sub {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.input-area {
  margin-bottom: 16px;
}
.examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}
.examples-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
}
.terminal-switch {
  margin: 0;
}
.approval-card {
  border-color: var(--el-color-warning-light-5);
  margin-bottom: 16px;
}
.approval-command {
  overflow-wrap: anywhere;
  margin-bottom: 10px;
}
.approval-command code {
  white-space: pre-wrap;
}
.approval-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-bottom: 10px;
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
.evidence-meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 4px;
}
.evidence-summary {
  margin-top: 4px;
  max-height: 72px;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--el-text-color-regular);
}
.evidence-raw {
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.evidence-collapse {
  border-top: none;
  --el-collapse-border-color: var(--el-border-color-lighter);
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
  padding: 2px 6px;
  border-radius: 6px;
  transition: background-color 0.25s ease;
}
.step-line .step-check {
  color: var(--el-color-success);
  margin-top: 3px;
  flex-shrink: 0;
}
.step-active {
  background-color: var(--el-color-primary-light-9);
  animation: step-breathe 1.6s ease-in-out infinite;
}
@keyframes step-breathe {
  0%, 100% { background-color: var(--el-color-primary-light-9); }
  50% { background-color: var(--el-color-primary-light-8); }
}
.step-tag {
  flex-shrink: 0;
}
.report-card {
  animation: card-rise 0.35s ease;
}
@keyframes card-rise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
/* ── 结构化结论卡 ── */
.diagnosis-result {
  margin-bottom: 14px;
}
.diagnosis-banner {
  padding: 14px 16px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
}
.diagnosis-banner-main {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.diagnosis-conclusion {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.5;
}
.diagnosis-banner-meta {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}
.diagnosis-sections {
  margin-top: 12px;
  display: grid;
  gap: 12px;
}
.diagnosis-section {
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.diagnosis-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.diagnosis-section-title .el-icon {
  color: var(--el-color-primary);
}
.diagnosis-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.diagnosis-item {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}
.diagnosis-item-meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.diagnosis-ref {
  padding: 0;
  height: auto;
  font-family: Consolas, Monaco, monospace;
}
.diagnosis-citations {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
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
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.hypo-rank {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
  font-size: 12px;
  flex-shrink: 0;
}
.hypo-rank.top {
  background: var(--el-color-primary);
  color: #fff;
}
.hypo-prob {
  color: #909399;
  font-variant-numeric: tabular-nums;
}
.hypo-prob.top {
  color: var(--el-color-primary);
  font-weight: 600;
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
.belief-chart {
  width: 100%;
  height: 280px;
}
/* ── 空状态 ── */
.empty-state {
  padding: 48px 0 32px;
  text-align: center;
}
.empty-icon {
  color: var(--el-text-color-placeholder);
}
.empty-title {
  margin: 12px 0 20px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
.empty-examples {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}
.example-card {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.example-card:hover:not(:disabled) {
  border-color: var(--el-color-primary-light-5);
  color: var(--el-color-primary);
  box-shadow: 0 2px 8px rgba(43, 125, 233, 0.12);
  transform: translateY(-1px);
}
.example-card:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
</style>
