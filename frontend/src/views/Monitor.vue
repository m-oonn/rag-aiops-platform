<template>
  <div>
    <h2>System Monitor</h2>
    
    <el-tabs v-model="activeTab">
      <el-tab-pane label="Queue Monitor" name="queue">
        <el-row :gutter="20" style="margin-bottom: 20px;">
          <el-col :span="6">
            <el-card shadow="hover">
              <template #header>Pending</template>
              <div class="stat-value">{{ stats.total_pending }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <template #header>Processing</template>
              <div class="stat-value processing">{{ stats.total_processing }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <template #header>Failed</template>
              <div class="stat-value failed">{{ stats.total_failed }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <template #header>Completed</template>
              <div class="stat-value success">{{ stats.total_completed }}</div>
            </el-card>
          </el-col>
        </el-row>

        <div class="filter-bar">
          <el-radio-group v-model="filterStatus" @change="fetchQueue">
            <el-radio-button label="">All</el-radio-button>
            <el-radio-button label="pending">Pending</el-radio-button>
            <el-radio-button label="processing">Processing</el-radio-button>
            <el-radio-button label="failed">Failed</el-radio-button>
          </el-radio-group>
          <el-button @click="fetchQueue" icon="Refresh" circle style="margin-left: 10px;"></el-button>
          <div style="flex: 1"></div>
          <el-button type="danger" @click="batchDelete" :disabled="!selectedQueueItems.length">Batch Delete</el-button>
        </div>

        <el-table :data="queueItems" style="width: 100%" v-loading="loading" @selection-change="handleQueueSelectionChange">
          <el-table-column type="selection" width="55" />
          <el-table-column prop="filename" label="File Name" />
          <el-table-column prop="kb_name" label="Knowledge Base" />
          <el-table-column prop="status" label="Status">
            <template #default="scope">
              <el-tag :type="getStatusType(scope.row.status)">{{ scope.row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Progress">
             <template #default="scope">
                 <el-progress :percentage="scope.row.progress" :status="scope.row.status === 'FAILURE' ? 'exception' : (scope.row.status === 'SUCCESS' ? 'success' : '')"></el-progress>
             </template>
          </el-table-column>
          <el-table-column prop="message" label="Message" show-overflow-tooltip />
          <el-table-column prop="created_at" label="Time">
              <template #default="scope">
                  {{ new Date(scope.row.created_at).toLocaleString() }}
              </template>
          </el-table-column>
          <el-table-column label="Actions">
              <template #default="scope">
                  <el-button size="small" type="danger" @click="deleteQueueItem(scope.row)">Delete</el-button>
              </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      
    <el-tab-pane label="MinIO Storage" name="minio">
        <div v-if="!minioConnected" style="text-align: center; padding: 20px;">
             <p>MinIO Access Required</p>
             <el-button type="primary" @click="minioLoginVisible = true">Login to MinIO</el-button>
             <p style="font-size: 0.8em; color: #999; margin-top: 10px;">Please login to MinIO first to view files.</p>
        </div>
        <div v-else>
            <div class="filter-bar">
               <el-input v-model="minioPrefix" placeholder="Search object name" style="width: 200px; margin-right: 10px;" @keyup.enter="fetchMinioFiles" />
               <el-button @click="fetchMinioFiles" icon="Refresh" circle></el-button>
               <el-button type="danger" @click="batchDeleteMinio" :disabled="!selectedMinioFiles.length">Batch Delete</el-button>
               <el-button @click="handleMinioLogout" type="text">Logout</el-button>
            </div>
            
            <el-table :data="minioFiles" style="width: 100%" v-loading="minioLoading" @selection-change="handleMinioSelectionChange">
               <el-table-column type="selection" width="55" />
               <el-table-column prop="object_name" label="Object Name" />
               <el-table-column prop="size" label="Size">
                   <template #default="scope">
                       {{ (scope.row.size / 1024).toFixed(2) }} KB
                   </template>
               </el-table-column>
               <el-table-column prop="last_modified" label="Last Modified">
                   <template #default="scope">
                       {{ new Date(scope.row.last_modified).toLocaleString() }}
                   </template>
               </el-table-column>
               <el-table-column label="Actions">
                   <template #default="scope">
                       <el-button size="small" @click="downloadFile(scope.row.object_name)">Download</el-button>
                       <el-button size="small" @click="viewFile(scope.row.object_name)">View</el-button>
                   </template>
               </el-table-column>
            </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
    
    <!-- MinIO Login Dialog -->
    <el-dialog v-model="minioLoginVisible" title="Login to MinIO" width="400px">
        <el-form :model="minioForm" label-width="100px">
            <el-form-item label="Endpoint">
                <el-input v-model="minioForm.endpoint" placeholder="localhost:9000" />
            </el-form-item>
            <el-form-item label="Access Key">
                <el-input v-model="minioForm.accessKey" />
            </el-form-item>
            <el-form-item label="Secret Key">
                <el-input v-model="minioForm.secretKey" type="password" show-password />
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="minioLoginVisible = false">Cancel</el-button>
            <el-button type="primary" @click="handleMinioLogin">Login</el-button>
        </template>
    </el-dialog>
    
    <!-- Preview Dialog -->
    <el-dialog v-model="previewVisible" title="File Preview" width="80%" top="5vh" class="preview-dialog">
        <div class="preview-header">
            <h3>{{ currentPreviewFile }}</h3>
        </div>
        <div class="preview-content">
            <iframe :src="previewUrl" style="width: 100%; height: 80vh; border: none;"></iframe>
        </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import api from '../api' // Assuming api.js exists and exports axios instance
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const activeTab = ref('queue')

// Queue Logic
const stats = ref({
  total_pending: 0,
  total_processing: 0,
  total_failed: 0,
  total_completed: 0
})
const queueItems = ref([])
const selectedQueueItems = ref([])
const loading = ref(false)
const filterStatus = ref('')
let pollTimer = null
const previewVisible = ref(false)
const previewUrl = ref('')
const currentPreviewFile = ref('')

const fetchStats = async () => {
  try {
      const res = await api.get('/monitor/stats')
      stats.value = res.data
  } catch (e) {
      console.error(e)
  }
}

const fetchQueue = async () => {
  loading.value = true
  try {
    const res = await api.get('/monitor/', { params: { status_filter: filterStatus.value || undefined } })
    queueItems.value = res.data
  } catch (e) {
      console.error(e)
  } finally {
    loading.value = false
  }
}

const refreshAll = async () => {
    if (activeTab.value !== 'queue') return
    await fetchStats()
    // Don't show loading on poll
    const res = await api.get('/monitor/', { params: { status_filter: filterStatus.value || undefined } })
    queueItems.value = res.data
}

const getStatusType = (status) => {
    if (status === 'SUCCESS') return 'success'
    if (status === 'FAILURE') return 'danger'
    if (status === 'PROCESSING') return 'warning'
    return 'info'
}

const handleQueueSelectionChange = (val) => {
    selectedQueueItems.value = val
}

const deleteQueueItem = async (row) => {
    try {
        await ElMessageBox.confirm('Are you sure to delete this task record?', 'Warning', { type: 'warning' })
        // Need backend API support for deleting task records
        // Assuming DELETE /monitor/tasks/{id}
        await api.delete(`/monitor/tasks/${row.task_id}`)
        ElMessage.success('Deleted')
        fetchQueue()
        fetchStats()
    } catch (e) {
        if (e !== 'cancel') ElMessage.error('Delete failed')
    }
}

const batchDelete = async () => {
    try {
        await ElMessageBox.confirm(`Delete ${selectedQueueItems.value.length} tasks?`, 'Warning', { type: 'warning' })
        const ids = selectedQueueItems.value.map(item => item.task_id)
        await api.post('/monitor/tasks/batch-delete', { task_ids: ids })
        ElMessage.success('Batch deleted')
        fetchQueue()
        fetchStats()
    } catch (e) {
        if (e !== 'cancel') ElMessage.error('Delete failed')
    }
}

// MinIO Logic
const minioFiles = ref([])
const minioLoading = ref(false)
const minioPrefix = ref('') // Used as search query now
const minioConnected = ref(false)
const minioLoginVisible = ref(false)
const selectedMinioFiles = ref([])
const minioForm = ref({
    endpoint: 'http://localhost:9000',
    accessKey: '',
    secretKey: ''
})

const handleMinioSelectionChange = (val) => {
    selectedMinioFiles.value = val
}

const batchDeleteMinio = async () => {
    try {
        await ElMessageBox.confirm(`Delete ${selectedMinioFiles.value.length} files?`, 'Warning', { type: 'warning' })
        const objectNames = selectedMinioFiles.value.map(item => item.object_name)
        await api.post('/storage/batch-delete', { object_names: objectNames })
        ElMessage.success('Batch deleted')
        fetchMinioFiles()
    } catch (e) {
        if (e !== 'cancel') ElMessage.error('Delete failed')
    }
}

const checkMinioAuth = () => {
    return localStorage.getItem('minio_auth_status') === 'connected'
}

const handleMinioLogin = () => {
    if (!minioForm.value.accessKey || !minioForm.value.secretKey) {
        ElMessage.warning('Please enter credentials')
        return
    }
    // Simulate login / connection check
    localStorage.setItem('minio_auth_status', 'connected')
    minioConnected.value = true
    minioLoginVisible.value = false
    fetchMinioFiles()
}

const handleMinioLogout = () => {
    localStorage.removeItem('minio_auth_status')
    minioConnected.value = false
}

const fetchMinioFiles = async () => {
    minioLoading.value = true
    try {
        // Use prefix as search query for fuzzy search
        const res = await api.get('/storage/files', { 
            params: { 
                search_query: minioPrefix.value,
                sort_by: 'last_modified',
                order: 'desc'
            } 
        })
        minioFiles.value = res.data.files
        minioConnected.value = true
    } catch (e) {
        console.error(e)
        ElMessage.error('Failed to fetch MinIO files')
    } finally {
        minioLoading.value = false
    }
}

const downloadFile = async (objectName) => {
    try {
        // Use proxy download endpoint
        const url = `/api/v1/storage/download/${encodeURIComponent(objectName)}`
        window.open(url, '_blank')
    } catch (e) {
        console.error(e)
        ElMessage.error('Failed to download file')
    }
}

const viewFile = async (objectName) => {
    try {
        currentPreviewFile.value = objectName
        // Use proxy preview endpoint
        // We need full URL for iframe
        const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
        // If baseUrl is relative, prepend origin
        let fullBase = baseUrl
        if (baseUrl.startsWith('/')) {
            fullBase = window.location.origin + baseUrl
        }
        
        previewUrl.value = `${fullBase}/storage/preview/${encodeURIComponent(objectName)}`
        previewVisible.value = true
    } catch (e) {
        console.error(e)
        ElMessage.error('Failed to open file')
    }
}

onMounted(() => {
  fetchStats()
  fetchQueue()
  
  if (activeTab.value === 'minio' && checkMinioAuth()) {
      minioConnected.value = true
      fetchMinioFiles()
  }
  
  pollTimer = setInterval(refreshAll, 3000)
})

watch(activeTab, (newTab) => {
    if (newTab === 'minio') {
        if (checkMinioAuth()) {
            minioConnected.value = true
            fetchMinioFiles()
        } else {
            minioLoginVisible.value = true
        }
    }
})

onUnmounted(() => {
    if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.stat-value {
    font-size: 24px;
    font-weight: bold;
    text-align: center;
}
.processing { color: #E6A23C; }
.failed { color: #F56C6C; }
.success { color: #67C23A; }
.filter-bar {
    margin-bottom: 20px;
    display: flex;
    align-items: center;
}
</style>
