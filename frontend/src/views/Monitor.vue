<template>
  <div>
    <h2>系统监控</h2>
    
    <el-tabs v-model="activeTab">
      <el-tab-pane label="队列监控" name="queue">
        <el-row :gutter="20" style="margin-bottom: 20px;">
          <el-col :span="6">
            <el-card shadow="hover">
              <template #header>待处理</template>
              <div class="stat-value">{{ stats.total_pending }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <template #header>处理中</template>
              <div class="stat-value processing">{{ stats.total_processing }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <template #header>失败</template>
              <div class="stat-value failed">{{ stats.total_failed }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <template #header>已完成</template>
              <div class="stat-value success">{{ stats.total_completed }}</div>
            </el-card>
          </el-col>
        </el-row>

        <div class="filter-bar">
          <el-radio-group v-model="filterStatus" @change="fetchQueue">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button value="pending">待处理</el-radio-button>
            <el-radio-button value="processing">处理中</el-radio-button>
            <el-radio-button value="failed">失败</el-radio-button>
          </el-radio-group>
          <el-button @click="fetchQueue" icon="Refresh" circle style="margin-left: 10px;"></el-button>
          <div style="flex: 1"></div>
          <el-button type="danger" @click="batchDelete" :disabled="!selectedQueueItems.length">批量删除</el-button>
        </div>

        <el-table :data="queueItems" style="width: 100%" v-loading="loading" @selection-change="handleQueueSelectionChange">
          <el-table-column type="selection" width="55" />
          <el-table-column prop="filename" label="文件名" />
          <el-table-column prop="kb_name" label="知识库" />
          <el-table-column prop="status" label="状态">
            <template #default="scope">
              <el-tag :type="getStatusType(scope.row.status)">{{ getQueueStatusText(scope.row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度">
             <template #default="scope">
                 <el-progress :percentage="scope.row.progress" :status="scope.row.status === 'FAILURE' ? 'exception' : (scope.row.status === 'SUCCESS' ? 'success' : '')"></el-progress>
             </template>
          </el-table-column>
          <el-table-column prop="message" label="信息" show-overflow-tooltip />
          <el-table-column prop="created_at" label="时间">
              <template #default="scope">
                  {{ formatDate(scope.row.created_at) }}
              </template>
          </el-table-column>
          <el-table-column label="操作">
              <template #default="scope">
                  <el-button size="small" type="danger" @click="deleteQueueItem(scope.row)">删除</el-button>
              </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      
    <el-tab-pane label="MinIO 存储" name="minio">
        <div v-if="!minioConnected" style="text-align: center; padding: 20px;">
             <p>需要 MinIO 访问权限</p>
             <el-button type="primary" @click="minioLoginVisible = true">登录 MinIO</el-button>
             <p style="font-size: 0.8em; color: #999; margin-top: 10px;">请先登录 MinIO 以查看文件。</p>
        </div>
        <div v-else>
            <div class="filter-bar">
               <el-input v-model="minioPrefix" placeholder="搜索对象名称" style="width: 200px; margin-right: 10px;" @keyup.enter="fetchMinioFiles" />
               <el-button @click="fetchMinioFiles" icon="Refresh" circle></el-button>
               <el-button type="danger" @click="batchDeleteMinio" :disabled="!selectedMinioFiles.length">批量删除</el-button>
               <el-button @click="handleMinioLogout" type="text">退出登录</el-button>
            </div>
            
            <el-table :data="minioFiles" style="width: 100%" v-loading="minioLoading" @selection-change="handleMinioSelectionChange">
               <el-table-column type="selection" width="55" />
               <el-table-column prop="object_name" label="对象名称" />
               <el-table-column prop="size" label="大小">
                   <template #default="scope">
                       {{ (scope.row.size / 1024).toFixed(2) }} KB
                   </template>
               </el-table-column>
               <el-table-column prop="last_modified" label="最后修改时间">
                   <template #default="scope">
                       {{ formatDate(scope.row.last_modified) }}
                   </template>
               </el-table-column>
               <el-table-column label="操作">
                   <template #default="scope">
                       <el-button size="small" @click="downloadFile(scope.row.object_name)">下载</el-button>
                       <el-button size="small" @click="viewFile(scope.row.object_name)">查看</el-button>
                   </template>
               </el-table-column>
            </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
    
    <!-- MinIO Login Dialog -->
    <el-dialog v-model="minioLoginVisible" title="登录 MinIO" width="400px">
        <el-form :model="minioForm" label-width="100px">
            <el-form-item label="端点">
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
            <el-button @click="minioLoginVisible = false">取消</el-button>
            <el-button type="primary" @click="handleMinioLogin">登录</el-button>
        </template>
    </el-dialog>
    
    <!-- Preview Dialog -->
    <el-dialog v-model="previewVisible" title="文件预览" width="80%" top="5vh" class="preview-dialog">
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
import { ref, onMounted, watch } from 'vue'
import api from '../api'
import { formatDate } from '../utils/format'
import { usePolling, POLL_FAST } from '../composables/usePolling'
import { confirmAction } from '../utils/confirm'
import { API_PREFIX } from '../utils/constants'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getQueueStatusType, getQueueStatusText as getQueueStatusTextFn } from '../utils/status'

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

const { start: startPolling } = usePolling(refreshAll, POLL_FAST)

const getStatusType = getQueueStatusType
const getQueueStatusText = getQueueStatusTextFn

const handleQueueSelectionChange = (val) => {
    selectedQueueItems.value = val
}

const deleteQueueItem = async (row) => {
    if (!(await confirmAction('确定要删除该任务记录吗？', '警告'))) return
    try {
        await api.delete(`/monitor/tasks/${row.task_id}`)
        ElMessage.success('删除成功')
        fetchQueue()
        fetchStats()
    } catch (e) {
        ElMessage.error('删除失败')
    }
}

const batchDelete = async () => {
    if (!(await confirmAction(`确定删除 ${selectedQueueItems.value.length} 个任务吗？`, '警告'))) return
    try {
        const ids = selectedQueueItems.value.map(item => item.task_id)
        await api.post('/monitor/tasks/batch-delete', { task_ids: ids })
        ElMessage.success('批量删除成功')
        fetchQueue()
        fetchStats()
    } catch (e) {
        ElMessage.error('删除失败')
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
    if (!(await confirmAction(`确定删除 ${selectedMinioFiles.value.length} 个文件吗？`, '警告'))) return
    try {
        const objectNames = selectedMinioFiles.value.map(item => item.object_name)
        await api.post('/storage/batch-delete', { object_names: objectNames })
        ElMessage.success('批量删除成功')
        fetchMinioFiles()
    } catch (e) {
        ElMessage.error('删除失败')
    }
}

const checkMinioAuth = () => {
    return localStorage.getItem('minio_auth_status') === 'connected'
}

const handleMinioLogin = () => {
    if (!minioForm.value.accessKey || !minioForm.value.secretKey) {
        ElMessage.warning('请输入凭证')
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
        ElMessage.error('获取 MinIO 文件失败')
    } finally {
        minioLoading.value = false
    }
}

const downloadFile = async (objectName) => {
    try {
        // Use proxy download endpoint
        const url = `${API_PREFIX}/storage/download/${encodeURIComponent(objectName)}`
        window.open(url, '_blank')
    } catch (e) {
        console.error(e)
        ElMessage.error('下载文件失败')
    }
}

const viewFile = async (objectName) => {
    try {
        currentPreviewFile.value = objectName
        // Use proxy preview endpoint
        // We need full URL for iframe
        const baseUrl = import.meta.env.VITE_API_BASE_URL || API_PREFIX
        // If baseUrl is relative, prepend origin
        let fullBase = baseUrl
        if (baseUrl.startsWith('/')) {
            fullBase = window.location.origin + baseUrl
        }
        
        previewUrl.value = `${fullBase}/storage/preview/${encodeURIComponent(objectName)}`
        previewVisible.value = true
    } catch (e) {
        console.error(e)
        ElMessage.error('打开文件失败')
    }
}

onMounted(() => {
  fetchStats()
  fetchQueue()
  
  if (activeTab.value === 'minio' && checkMinioAuth()) {
      minioConnected.value = true
      fetchMinioFiles()
  }

  startPolling()
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
