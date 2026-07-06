<template>
  <div class="queue-monitor">
    <div class="header">
      <h2>队列管理</h2>
      <el-button @click="fetchStats" :loading="loading">刷新</el-button>
    </div>

    <div v-if="error" class="error-msg">
      <el-alert :title="error" type="error" show-icon />
    </div>

    <div v-if="stats" class="stats-container">
      <el-row :gutter="20">
        <el-col :span="8">
          <el-card shadow="always">
            <template #header>
              <div class="card-header">
                <span>活跃任务</span>
              </div>
            </template>
            <div class="stat-value">{{ stats.summary.active_tasks }}</div>
            <div class="stat-desc">当前正在执行</div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="always">
            <template #header>
              <div class="card-header">
                <span>预留任务</span>
              </div>
            </template>
            <div class="stat-value">{{ stats.summary.reserved_tasks }}</div>
            <div class="stat-desc">已被 Worker 预取</div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="always">
            <template #header>
              <div class="card-header">
                <span>计划任务</span>
              </div>
            </template>
            <div class="stat-value">{{ stats.summary.scheduled_tasks }}</div>
            <div class="stat-desc">延迟/重试中</div>
          </el-card>
        </el-col>
      </el-row>

      <el-divider content-position="left">Worker 详情</el-divider>

      <div v-for="(workerStats, workerName) in stats.details.worker_stats" :key="workerName" class="worker-card">
        <el-descriptions :title="`Worker：${workerName}`" border>
          <el-descriptions-item label="并发上限">{{ workerStats.pool['max-concurrency'] }}</el-descriptions-item>
          <el-descriptions-item label="进程数">{{ workerStats.pool.processes.length }}</el-descriptions-item>
          <el-descriptions-item label="运行时间">{{ workerStats.uptime }}s</el-descriptions-item>
        </el-descriptions>
        
        <div style="margin-top: 10px;" v-if="stats.details.active[workerName] && stats.details.active[workerName].length > 0">
           <h4>活跃任务：</h4>
           <el-table :data="stats.details.active[workerName]" style="width: 100%" size="small">
              <el-table-column prop="name" label="任务名称" />
              <el-table-column prop="id" label="ID" width="300" />
              <el-table-column prop="time_start" label="开始时间" />
              <el-table-column label="参数">
                  <template #default="scope">
                      {{ scope.row.args }}
                  </template>
              </el-table-column>
           </el-table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'
import { usePolling, POLL_SLOW } from '../composables/usePolling'

const stats = ref(null)
const loading = ref(false)
const error = ref(null)

const fetchStats = async () => {
  loading.value = true
  error.value = null
  try {
    const res = await api.get('/health/queues')
    if (res.data.status === 'error') {
        error.value = res.data.message
    } else {
        stats.value = res.data
    }
  } catch (e) {
    error.value = '获取队列统计失败'
  } finally {
    loading.value = false
  }
}

const { start: startPolling } = usePolling(fetchStats, POLL_SLOW)

onMounted(() => {
  fetchStats()
  startPolling()
})
</script>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.stat-value {
  font-size: 32px;
  font-weight: bold;
  color: #409EFF;
  text-align: center;
}
.stat-desc {
  text-align: center;
  color: #909399;
}
.worker-card {
  margin-top: 20px;
  background: #fff;
  padding: 15px;
  border-radius: 4px;
  border: 1px solid #EBEEF5;
}
</style>
