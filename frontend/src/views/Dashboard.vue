<template>
  <div class="dashboard">
    <!-- 顶部欢迎 + 快捷操作 -->
    <PageHeader title="工作台" subtitle="AIOps 智能体平台 · 故障诊断 / 知识问答 / 效果评测">
      <template #actions>
        <el-button type="primary" @click="$router.push('/aiops')">
          <el-icon><Monitor /></el-icon>&nbsp;开始故障诊断
        </el-button>
        <el-button @click="$router.push('/chat')">新建会话</el-button>
      </template>
    </PageHeader>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :xs="24" :sm="12" :md="6" v-for="s in stats" :key="s.label">
        <el-card shadow="hover" class="stat-card" @click="$router.push(s.route)">
          <div class="stat-inner">
            <div class="stat-icon" :style="{ background: s.bg, color: s.color }">
              <el-icon :size="22"><component :is="s.icon" /></el-icon>
            </div>
            <div class="stat-body">
              <div class="stat-value">
                {{ s.value }}<span class="stat-unit" v-if="s.unit">{{ s.unit }}</span>
              </div>
              <div class="stat-label">{{ s.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <!-- 服务状态 -->
      <el-col :xs="24" :md="14">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-header">
              <span>服务状态</span>
              <el-tag :type="depOverall === 'ok' ? 'success' : 'warning'" size="small" effect="plain">
                {{ depOverallText }}
              </el-tag>
            </div>
          </template>
          <div v-if="deps.length" class="dep-grid">
            <div class="dep-item" v-for="d in deps" :key="d.key">
              <span class="dep-dot" :class="d.status"></span>
              <span class="dep-name">{{ d.name }}</span>
              <span class="dep-status" :class="d.status">{{ d.statusText }}</span>
            </div>
          </div>
          <div v-else class="dep-placeholder">
            <el-skeleton v-if="!depLoaded" :rows="3" animated />
            <el-empty v-else description="暂时无法获取服务状态" :image-size="60" />
          </div>
        </el-card>
      </el-col>

      <!-- 快捷入口 -->
      <el-col :xs="24" :md="10">
        <el-card shadow="never" class="panel">
          <template #header><span>快捷入口</span></template>
          <div class="quick-list">
            <div class="quick-item" v-for="q in quicks" :key="q.label" @click="$router.push(q.route)">
              <el-icon :size="18" :style="{ color: q.color }"><component :is="q.icon" /></el-icon>
              <div class="quick-text">
                <div class="quick-label">{{ q.label }}</div>
                <div class="quick-desc">{{ q.desc }}</div>
              </div>
              <el-icon class="quick-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, markRaw } from 'vue'
import {
  Monitor, DataLine, Tickets, Document, Collection,
  ChatDotRound, Odometer, DataAnalysis, ArrowRight
} from '@element-plus/icons-vue'
import api from '../api'
import PageHeader from '../components/PageHeader.vue'

const stats = ref([
  { key: 'kb', label: '知识库', value: '-', unit: '个', icon: markRaw(Collection), bg: '#e8f3ff', color: '#2b7de9', route: '/knowledge-bases' },
  { key: 'docs', label: '知识文档', value: '-', unit: '份', icon: markRaw(Document), bg: '#e8f8ee', color: '#27a35d', route: '/knowledge-bases' },
  { key: 'queue', label: '待处理任务', value: '-', unit: '个', icon: markRaw(Tickets), bg: '#fff4e6', color: '#e08a1e', route: '/monitor' },
  { key: 'eval', label: '评测任务', value: '-', unit: '个', icon: markRaw(DataAnalysis), bg: '#f3ecff', color: '#7b57d9', route: '/evaluation' },
])

const quicks = [
  { label: '故障诊断', desc: '描述故障现象，智能体自动排查', route: '/aiops', icon: markRaw(Monitor), color: '#2b7de9' },
  { label: '知识问答', desc: '基于知识库的检索增强问答', route: '/chat', icon: markRaw(ChatDotRound), color: '#27a35d' },
  { label: '效果评测', desc: '对问答效果进行量化打分', route: '/evaluation', icon: markRaw(DataLine), color: '#7b57d9' },
  { label: '系统监控', desc: '任务队列与运行状态', route: '/monitor', icon: markRaw(Odometer), color: '#e08a1e' },
]

const deps = ref([])
const depLoaded = ref(false)
const depOverall = ref('')
const depOverallText = ref('检测中')

const DEP_META = {
  mcp_monitor: '监控指标服务',
  mcp_cls: '日志检索服务',
  rabbitmq: '任务队列',
  redis: '缓存',
  milvus: '向量库',
  minio: '文件存储',
  llm: '大模型',
}

function setStat(key, value) {
  const s = stats.value.find((x) => x.key === key)
  if (s) s.value = value
}

async function loadStats() {
  // 知识库与文档
  try {
    const { data: kbs } = await api.get('/knowledge-bases/')
    setStat('kb', kbs.length)
    let total = 0
    for (const kb of kbs.slice(0, 10)) {
      try {
        const { data: docs } = await api.get(`/knowledge-bases/${kb.id}/documents`)
        total += docs.length
      } catch (e) { /* 单个知识库不可达时跳过 */ }
    }
    setStat('docs', total)
  } catch (e) {
    setStat('kb', '—')
    setStat('docs', '—')
  }
  // 任务队列
  try {
    const { data: q } = await api.get('/monitor/stats')
    setStat('queue', (q.total_pending || 0) + (q.total_processing || 0))
  } catch (e) {
    setStat('queue', '—')
  }
  // 评测任务
  try {
    const { data: tasks } = await api.get('/evaluations/tasks')
    setStat('eval', tasks.length)
  } catch (e) {
    setStat('eval', '—')
  }
}

async function loadDeps() {
  try {
    const { data } = await api.get('/health/dependencies')
    const services = data.services || {}
    deps.value = Object.keys(DEP_META).map((k) => {
      const s = services[k] || { status: 'unknown' }
      return {
        key: k,
        name: DEP_META[k],
        status: s.status,
        statusText: s.status === 'ok' ? '正常' : s.status === 'degraded' ? '降级' : '不可用',
      }
    })
    depOverall.value = data.overall
    depOverallText.value = data.overall === 'ok' ? '全部正常' : '部分降级'
  } catch (e) {
    depOverallText.value = '检测失败'
  } finally {
    depLoaded.value = true
  }
}

onMounted(() => {
  loadStats()
  loadDeps()
})
</script>

<style scoped>
.dashboard {
  padding: 4px;
}
.stat-row {
  margin-bottom: 4px;
}
.stat-card {
  cursor: pointer;
  transition: box-shadow 0.2s ease;
}
.stat-card:hover {
  box-shadow: var(--app-shadow-card-hover);
}
.stat-inner {
  display: flex;
  align-items: center;
  gap: 14px;
}
.stat-icon {
  width: 46px;
  height: 46px;
  border-radius: var(--app-radius-control);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--app-text-primary);
  line-height: 1.2;
}
.stat-unit {
  font-size: 13px;
  font-weight: 400;
  color: var(--app-text-secondary);
  margin-left: 2px;
}
.stat-label {
  font-size: 13px;
  color: var(--app-text-secondary);
  margin-top: 2px;
}

.panel {
  margin-top: var(--app-gap-section);
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.dep-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px 24px;
}
.dep-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--app-radius-control);
  background: var(--app-bg-subtle);
}
.dep-placeholder {
  padding: 4px 0;
}
.dep-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}
.dep-dot.ok {
  background: #27a35d;
}
.dep-dot.degraded {
  background: #e08a1e;
}
.dep-dot.unavailable,
.dep-dot.unknown {
  background: #c9ced6;
}
.dep-name {
  flex: 1;
  font-size: 13px;
  color: #33405a;
}
.dep-status {
  font-size: 12px;
}
.dep-status.ok {
  color: #27a35d;
}
.dep-status.degraded {
  color: #e08a1e;
}
.dep-status.unavailable,
.dep-status.unknown {
  color: var(--app-text-secondary);
}

.quick-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.quick-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 8px;
  border-radius: var(--app-radius-control);
  cursor: pointer;
  transition: background 0.15s;
}
.quick-item:hover {
  background: #f4f7fb;
}
.quick-text {
  flex: 1;
  min-width: 0;
}
.quick-label {
  font-size: 14px;
  color: var(--app-text-primary);
}
.quick-desc {
  font-size: 12px;
  color: var(--app-text-secondary);
  margin-top: 2px;
}
.quick-arrow {
  color: var(--app-text-tertiary);
}

/* 窄屏：统计卡与面板纵向堆叠时去掉多余的顶部间距 */
@media (max-width: 991px) {
  .panel {
    margin-top: var(--app-gap-section);
  }
}
</style>
