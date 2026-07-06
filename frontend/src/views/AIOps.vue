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
        placeholder="描述故障现象或诊断任务，例如：订单服务 5xx 突增，帮我定位原因"
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
          {{ step.text }}
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

    <el-empty v-if="!steps.length && !running && !report" description="输入故障现象，开始诊断" />
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Document } from '@element-plus/icons-vue'
import { streamSSE } from '../utils/sse'
import { getAiopsStreamUrl } from '../utils/chat'

const query = ref('')
const sessionId = ref('web-' + Math.random().toString(36).slice(2, 10))
const running = ref(false)
const steps = ref([])        // [{ text, done }]
const report = ref('')
const statusText = ref('')
const errorMsg = ref('')
let abortController = null

const examples = [
  'CPU 使用率飙升，帮我定位是哪个进程',
  '订单服务 5xx 突增，排查根因',
  '磁盘空间告警，找出占用大的目录',
]

const doneCount = computed(() => steps.value.filter((s) => s.done).length)

// 简单 Markdown 渲染：标题 / 列表 / 加粗 / 换行
const renderedReport = computed(() => {
  let text = report.value || ''
  // 转义 HTML
  text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  // 标题
  text = text.replace(/^### (.*$)/gim, '<h4>$1</h4>')
  text = text.replace(/^## (.*$)/gim, '<h3>$1</h3>')
  text = text.replace(/^# (.*$)/gim, '<h2>$1</h2>')
  // 加粗
  text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  // 列表
  text = text.replace(/^\s*[-*]\s+(.*$)/gim, '<li>$1</li>')
  // 段落
  text = text.split(/\n{2,}/).map((p) => {
    if (p.startsWith('<h') || p.startsWith('<li')) return p
    return `<p>${p.replace(/\n/g, '<br/>')}</p>`
  }).join('')
  return text
})

const resetState = () => {
  steps.value = []
  report.value = ''
  statusText.value = ''
  errorMsg.value = ''
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
      steps.value = (evt.plan || []).map((text) => ({ text, done: false }))
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
.report-body {
  line-height: 1.7;
  color: #303133;
}
.report-body :deep(h2) {
  font-size: 18px;
  margin: 16px 0 8px;
}
.report-body :deep(h3) {
  font-size: 16px;
  margin: 14px 0 6px;
}
.report-body :deep(p) {
  margin: 8px 0;
}
.report-body :deep(li) {
  margin-left: 18px;
  list-style: disc;
}
</style>
