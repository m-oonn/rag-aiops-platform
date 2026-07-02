<template>
  <div class="aiops-container">
    <div class="header-row">
      <h2>AIOps 运维诊断</h2>
      <el-tag type="info" effect="plain">Plan-Execute-Replan Agent</el-tag>
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
        <el-button type="primary" :loading="running" @click="runDiagnose">
          {{ running ? '诊断中...' : '开始诊断' }}
        </el-button>
      </div>
    </div>

    <!-- 状态行 -->
    <el-alert
      v-if="statusText"
      :title="statusText"
      :type="errorMsg ? 'error' : 'info'"
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
        <el-icon><Document /></el-icon>
        <span style="margin-left: 6px;">诊断报告</span>
      </template>
      <div class="report-body">{{ report }}</div>
    </el-card>

    <el-empty v-if="!steps.length && !running && !report" description="输入故障现象，开始诊断" />
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Document } from '@element-plus/icons-vue'

const query = ref('')
const sessionId = ref('web-' + Math.random().toString(36).slice(2, 10))
const running = ref(false)
const steps = ref([])        // [{ text, done }]
const report = ref('')
const statusText = ref('')
const errorMsg = ref('')

const examples = [
  'CPU 使用率飙升，帮我定位是哪个进程',
  '订单服务 5xx 突增，排查根因',
  '磁盘空间告警，找出占用大的目录',
]

const doneCount = computed(() => steps.value.filter((s) => s.done).length)

const resetState = () => {
  steps.value = []
  report.value = ''
  statusText.value = ''
  errorMsg.value = ''
}

// 按 type 分发单条 SSE 事件到本地状态
const handleEvent = (evt) => {
  switch (evt.type) {
    case 'plan':
      steps.value = (evt.plan || []).map((text) => ({ text, done: false }))
      statusText.value = evt.message || '诊断计划已制定'
      break
    case 'step_complete': {
      // 点亮下一个未完成的节点
      const next = steps.value.find((s) => !s.done)
      if (next) next.done = true
      statusText.value = evt.message || '步骤完成'
      break
    }
    case 'status':
      statusText.value = evt.message || ''
      break
    case 'report':
      report.value = evt.report || ''
      statusText.value = evt.message || '诊断报告已生成'
      break
    case 'complete':
      // 收尾：若过程中未拿到 report，用 complete 的 response 兜底
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

// fetch + ReadableStream 手动解析 SSE（端点是 POST，原生 EventSource 只支持 GET）
const runDiagnose = async () => {
  if (!query.value.trim() || running.value) return
  resetState()
  running.value = true

  try {
    const res = await fetch('/api/v1/aiops', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query.value, session_id: sessionId.value }),
    })
    if (!res.ok || !res.body) {
      throw new Error(`请求失败: HTTP ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      // sse_starlette 用 \r\n 作行分隔，统一成 \n 再按空行分帧
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

      // SSE 以空行分帧
      const frames = buffer.split('\n\n')
      buffer = frames.pop() || ''
      for (const frame of frames) {
        const dataLine = frame
          .split('\n')
          .find((l) => l.startsWith('data:'))
        if (!dataLine) continue
        const payload = dataLine.slice(5).trim()
        if (!payload) continue
        try {
          handleEvent(JSON.parse(payload))
        } catch (e) {
          console.warn('无法解析 SSE 帧:', payload)
        }
      }
    }
  } catch (e) {
    errorMsg.value = e.message || '诊断请求异常'
    statusText.value = errorMsg.value
    ElMessage.error(errorMsg.value)
  } finally {
    running.value = false
  }
}
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
.status-alert {
  margin-bottom: 16px;
}
.section-card {
  margin-bottom: 16px;
}
.report-card :deep(.el-card__header) {
  display: flex;
  align-items: center;
}
.report-body {
  white-space: pre-wrap;
  line-height: 1.7;
  color: #303133;
}
</style>
