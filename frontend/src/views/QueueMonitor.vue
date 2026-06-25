<template>
  <div class="queue-monitor">
    <div class="header">
      <h2>Queue Management</h2>
      <el-button @click="fetchStats" :loading="loading">Refresh</el-button>
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
                <span>Active Tasks</span>
              </div>
            </template>
            <div class="stat-value">{{ stats.summary.active_tasks }}</div>
            <div class="stat-desc">Currently executing</div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="always">
            <template #header>
              <div class="card-header">
                <span>Reserved Tasks</span>
              </div>
            </template>
            <div class="stat-value">{{ stats.summary.reserved_tasks }}</div>
            <div class="stat-desc">Prefetched by workers</div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="always">
            <template #header>
              <div class="card-header">
                <span>Scheduled Tasks</span>
              </div>
            </template>
            <div class="stat-value">{{ stats.summary.scheduled_tasks }}</div>
            <div class="stat-desc">Delayed/Retrying</div>
          </el-card>
        </el-col>
      </el-row>

      <el-divider content-position="left">Worker Details</el-divider>

      <div v-for="(workerStats, workerName) in stats.details.worker_stats" :key="workerName" class="worker-card">
        <el-descriptions :title="`Worker: ${workerName}`" border>
          <el-descriptions-item label="Pool Size">{{ workerStats.pool.max-concurrency }}</el-descriptions-item>
          <el-descriptions-item label="Processes">{{ workerStats.pool.processes.length }}</el-descriptions-item>
          <el-descriptions-item label="Uptime">{{ workerStats.uptime }}s</el-descriptions-item>
        </el-descriptions>
        
        <div style="margin-top: 10px;" v-if="stats.details.active[workerName] && stats.details.active[workerName].length > 0">
           <h4>Active Tasks:</h4>
           <el-table :data="stats.details.active[workerName]" style="width: 100%" size="small">
              <el-table-column prop="name" label="Task Name" />
              <el-table-column prop="id" label="ID" width="300" />
              <el-table-column prop="time_start" label="Started At" />
              <el-table-column label="Args">
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
import { ref, onMounted, onUnmounted } from 'vue'
import api from '../api'

const stats = ref(null)
const loading = ref(false)
const error = ref(null)
let timer = null

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
    error.value = 'Failed to fetch queue stats'
  } finally {
    loading.value = false
  }
}

const startPolling = () => {
  stopPolling()
  timer = setInterval(fetchStats, 5000)
}

const stopPolling = () => {
  if (timer) clearInterval(timer)
}

onMounted(() => {
  fetchStats()
  startPolling()
})

onUnmounted(stopPolling)
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
