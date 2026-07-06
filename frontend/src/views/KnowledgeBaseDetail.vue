<template>
  <div class="kb-detail">
    <div class="header">
      <el-button @click="$router.push('/knowledge-bases')" icon="Back" circle></el-button>
      <h2>{{ kb.name }}</h2>
      <span class="desc">{{ kb.description }}</span>
    </div>

    <div class="actions-bar">
      <el-upload
        class="upload-demo"
        :action="`${API_PREFIX}/knowledge-bases/${kbId}/upload`"
        :headers="headers"
        multiple
        :on-success="handleUploadSuccess"
        :on-error="handleUploadError"
        :on-progress="handleUploadProgress"
        :file-list="fileList"
        :show-file-list="false"
        style="display: inline-block; margin-right: 10px;"
      >
        <el-button type="primary" icon="Upload">批量上传</el-button>
      </el-upload>
      
      <el-button type="warning" @click="batchRetry" :disabled="!selectedDocs.length" icon="Refresh">批量重试</el-button>
      <el-button type="danger" @click="batchDelete" :disabled="!selectedDocs.length" icon="Delete">批量删除</el-button>
      <el-button @click="fetchDocuments" icon="RefreshRight">刷新列表</el-button>
    </div>

    <!-- Upload Queue Monitor -->
    <el-collapse v-if="uploadQueue.length > 0" v-model="activeNames" style="margin-bottom: 20px;">
      <el-collapse-item title="上传队列" name="1">
        <el-table :data="uploadQueue" style="width: 100%" size="small">
          <el-table-column prop="name" label="文件名" />
          <el-table-column label="进度" width="300">
            <template #default="scope">
              <el-progress :percentage="scope.row.percentage" :status="scope.row.status === 'success' ? 'success' : (scope.row.status === 'fail' ? 'exception' : '')" />
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100" />
        </el-table>
      </el-collapse-item>
    </el-collapse>

    <!-- Document List -->
    <el-table 
      :data="documents" 
      @selection-change="handleSelectionChange"
      v-loading="loading"
      style="width: 100%"
    >
      <el-table-column type="selection" width="55" />
      <el-table-column prop="filename" label="文件名" min-width="200" />
      <el-table-column prop="file_size" label="大小">
        <template #default="scope">
          {{ scope.row.file_size ? formatSize(scope.row.file_size) : 'Unknown' }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="120">
        <template #default="scope">
          <el-tag :type="getStatusType(scope.row.status)">
            {{ getStatusText(scope.row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="分片数" width="100" />
      <el-table-column prop="created_at" label="上传时间">
        <template #default="scope">
          {{ formatDate(scope.row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="250" fixed="right">
        <template #default="scope">
          <el-button size="small" @click="generateQA(scope.row)">生成 QA</el-button>
          <el-button size="small" @click="viewQA(scope.row)">管理 QA</el-button>
          <el-button size="small" @click="viewChunks(scope.row)">分片</el-button>
          <el-button size="small" @click="previewFile(scope.row)">预览</el-button>
          <el-button size="small" type="primary" @click="openReprocessDialog(scope.row)">重新切分</el-button>
          <el-button size="small" type="warning" @click="retryDoc(scope.row)" v-if="scope.row.status === 3">重试</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Preview Dialog -->
    <el-dialog v-model="previewVisible" title="文件预览" width="80%" top="5vh" class="preview-dialog">
        <div class="preview-header">
            <h3>{{ currentPreviewFile?.filename }}</h3>
        </div>
        <div class="preview-content">
            <iframe :src="previewUrl" style="width: 100%; height: 80vh; border: none;"></iframe>
        </div>
    </el-dialog>

    <!-- Reprocess Dialog -->
    <el-dialog v-model="reprocessVisible" title="重新处理文档" width="30%">
        <el-form :model="reprocessForm" label-width="120px">
            <el-form-item label="切分策略">
                <el-select v-model="reprocessForm.strategy">
                    <el-option label="递归切分" value="recursive" />
                    <el-option label="固定长度" value="fixed" />
                    <el-option label="分隔符" value="separator" />
                    <el-option label="语义切分" value="semantic" />
                </el-select>
            </el-form-item>
            <el-form-item label="块大小">
                <el-input-number v-model="reprocessForm.chunk_size" :min="100" :max="2000" :step="100" />
            </el-form-item>
            <el-form-item label="重叠长度">
                <el-input-number v-model="reprocessForm.chunk_overlap" :min="0" :max="500" :step="10" />
            </el-form-item>
            <el-form-item label="分隔符" v-if="reprocessForm.strategy === 'separator'">
                <el-input v-model="reprocessForm.separator" placeholder="\n\n" />
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="reprocessVisible = false">取消</el-button>
            <el-button type="primary" @click="startReprocess" :loading="isProcessing">开始</el-button>
        </template>
    </el-dialog>

    <!-- Progress Dialog for Long Running Tasks -->
    <el-dialog v-model="isProcessing" :title="processingStatus" width="30%" :close-on-click-modal="false" :show-close="false">
        <el-progress :percentage="processingPercentage" :status="processingPercentage === 100 ? 'success' : ''" />
        <div style="margin-top: 10px; text-align: center;">请稍候...</div>
    </el-dialog>

    <!-- QA Dialog -->
    <el-dialog v-model="qaVisible" title="管理 QA 对" width="80%">
      <div style="margin-bottom: 10px; display: flex; justify-content: space-between;">
        <el-button type="primary" @click="openQAForm()">新增 QA 对</el-button>
        <el-button type="success" @click="downloadQA(currentDocId)">下载 MD</el-button>
      </div>
      <el-table :data="qaPairs" height="400">
        <el-table-column prop="question" label="问题" min-width="200" />
        <el-table-column prop="answer" label="答案" min-width="200" />
        <el-table-column prop="qa_type" label="类型" width="120">
             <template #default="scope">
                 <el-tag>{{ scope.row.qa_type }}</el-tag>
             </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
            <template #default="scope">
                <el-button size="small" @click="openQAForm(scope.row)">编辑</el-button>
                <el-button size="small" type="danger" @click="deleteQA(scope.row.id)">删除</el-button>
            </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- QA Form Dialog -->
    <el-dialog v-model="qaFormVisible" :title="isEditQA ? '编辑 QA 对' : '新增 QA 对'" width="50%">
        <el-form :model="qaForm" label-width="100px">
            <el-form-item label="类型">
                <el-select v-model="qaForm.qa_type" allow-create filterable default-first-option placeholder="选择或输入标签">
                    <el-option label="单跳" value="single_hop" />
                    <el-option label="多跳" value="multi_hop" />
                    <el-option label="摘要" value="summary" />
                    <el-option label="通用" value="general" />
                </el-select>
            </el-form-item>
            <el-form-item label="问题">
                <el-input v-model="qaForm.question" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="答案">
                <el-input v-model="qaForm.answer" type="textarea" :rows="4" />
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="qaFormVisible = false">取消</el-button>
            <el-button type="primary" @click="saveQA">保存</el-button>
        </template>
    </el-dialog>

    <!-- Chunks Dialog -->
    <el-dialog v-model="chunksVisible" title="文档分片" width="70%">
      <el-table :data="chunks" height="400">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="content" label="内容" />
        <el-table-column prop="page_num" label="页码" width="80" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api'
import { Back, Upload, Refresh, Delete, RefreshRight, View, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getNumericStatusType, getDocStatusText } from '../utils/status'
import { formatDate, formatSize } from '../utils/format'
import { usePolling, POLL_FAST } from '../composables/usePolling'
import { confirmAction } from '../utils/confirm'
import { API_PREFIX } from '../utils/constants'

const route = useRoute()
const router = useRouter()
const kbId = route.params.id
const kb = ref({})
const documents = ref([])
const selectedDocs = ref([])
const loading = ref(false)
const qaVisible = ref(false)
const qaPairs = ref([])
const chunksVisible = ref(false)
const chunks = ref([])

// Preview
const previewVisible = ref(false)
const previewUrl = ref('')
const currentPreviewFile = ref(null)

// Reprocess
const reprocessVisible = ref(false)
const currentDocId = ref(null)
const reprocessForm = reactive({
    strategy: 'recursive',
    chunk_size: 1000,
    chunk_overlap: 200,
    separator: ''
})

// Progress tracking
const processingStatus = ref('')
const processingPercentage = ref(0)
const isProcessing = ref(false)

// QA
const currentQAId = ref(null)
const isEditQA = ref(false)
const qaFormVisible = ref(false)
const qaForm = reactive({
    question: '',
    answer: '',
    qa_type: 'single_hop'
})

// Upload Queue
const fileList = ref([])
const uploadQueue = ref([])
const activeNames = ref(['1'])

const headers = computed(() => ({
  Authorization: `Bearer ${localStorage.getItem('token')}`
}))

const fetchKB = async () => {
  try {
    const res = await api.get(`/knowledge-bases/${kbId}`)
    kb.value = res.data
  } catch (e) {
    ElMessage.error('加载知识库详情失败')
    router.push('/knowledge-bases')
  }
}

const fetchDocuments = async () => {
  loading.value = true
  try {
    const res = await api.get(`/knowledge-bases/${kbId}/documents`)
    documents.value = res.data
  } catch (e) {
    ElMessage.error('加载文档失败')
  } finally {
    loading.value = false
  }
}

// Polling for document status updates (Processing Queue Monitor)
const pollDocuments = async () => {
    // Only poll if there are documents in processing state (1) or uploading (0)
    const pendingDocs = documents.value.some(d => d.status === 0 || d.status === 1)
    if (pendingDocs || uploadQueue.value.length > 0) {
        // Silent refresh
        try {
            const res = await api.get(`/knowledge-bases/${kbId}/documents`)
            documents.value = res.data
        } catch (e) {}
    }
}

const { start: startPolling } = usePolling(pollDocuments, POLL_FAST)

const handleUploadProgress = (event, file, fileList) => {
  const existing = uploadQueue.value.find(f => f.uid === file.uid)
  if (existing) {
    existing.percentage = Math.round(event.percent)
    existing.status = 'uploading'
  } else {
    uploadQueue.value.push({
      uid: file.uid,
      name: file.name,
      percentage: Math.round(event.percent),
      status: 'uploading'
    })
  }
}

const handleUploadSuccess = (response, file, fileList) => {
  const existing = uploadQueue.value.find(f => f.uid === file.uid)
  if (existing) {
    existing.percentage = 100
    existing.status = 'success'
    // Remove from queue after a delay
    setTimeout(() => {
      uploadQueue.value = uploadQueue.value.filter(f => f.uid !== file.uid)
    }, 3000)
  }
  ElMessage.success(`文件 ${file.name} 上传成功`)
  fetchDocuments()
}

const handleUploadError = (err, file, fileList) => {
  const existing = uploadQueue.value.find(f => f.uid === file.uid)
  if (existing) {
    existing.status = 'fail'
    existing.percentage = 0
  }
  ElMessage.error(`文件 ${file.name} 上传失败`)
}

const handleSelectionChange = (val) => {
  selectedDocs.value = val
}

const batchRetry = async () => {
  try {
    const ids = selectedDocs.value.map(d => d.id)
    await api.post('/knowledge-bases/documents/batch-retry', ids)
    ElMessage.success('批量重试已开始')
    fetchDocuments()
  } catch (e) {
    ElMessage.error('批量重试失败')
  }
}

const batchDelete = async () => {
  if (!(await confirmAction('确定要删除所选文档吗？', '警告'))) return
  try {
    const ids = selectedDocs.value.map(d => d.id)
    await api.delete('/knowledge-bases/documents/batch-delete', { data: ids })
    ElMessage.success('文档已删除')
    fetchDocuments()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

const retryDoc = async (row) => {
  try {
    await api.post(`/knowledge-bases/documents/${row.id}/retry`)
    ElMessage.success('重试已开始')
    fetchDocuments()
  } catch (e) {
    ElMessage.error('重试失败')
  }
}

const generateQA = async (row) => {
    try {
        ElMessageBox.prompt('要生成多少对 QA？', '生成 QA', {
            confirmButtonText: '生成',
            cancelButtonText: '取消',
            inputPattern: /^[1-9]\d*$/,
            inputErrorMessage: '请输入有效数字',
            inputValue: row.chunk_count > 0 ? row.chunk_count : 5
        }).then(async ({ value }) => {
            isProcessing.value = true
            processingStatus.value = '正在生成 QA...'
            processingPercentage.value = 0
            
            const progressTimer = setInterval(() => {
                if (processingPercentage.value < 90) {
                    processingPercentage.value += 5
                }
            }, 500)
            
            await api.post(`/knowledge-bases/documents/${row.id}/generate-qa`, null, { params: { num_pairs: value } })
            
            clearInterval(progressTimer)
            processingPercentage.value = 100
            processingStatus.value = '已完成'
            ElMessage.success('QA 生成完成')
            
            setTimeout(() => { isProcessing.value = false }, 1000)
        }).catch(() => {
             // Catch cancel
        })
    } catch (e) {
        ElMessage.error('QA 生成失败')
        isProcessing.value = false
    }
}

const viewQA = async (row) => {
  currentDocId.value = row.id
  try {
    const res = await api.get(`/knowledge-bases/documents/${row.id}/qa-pairs`)
    qaPairs.value = res.data
    qaVisible.value = true
  } catch (e) {
    ElMessage.error('加载 QA 对失败')
  }
}

const openQAForm = (qa = null) => {
    if (qa) {
        isEditQA.value = true
        currentQAId.value = qa.id
        qaForm.question = qa.question
        qaForm.answer = qa.answer
        qaForm.qa_type = qa.qa_type
    } else {
        isEditQA.value = false
        currentQAId.value = null
        qaForm.question = ''
        qaForm.answer = ''
        qaForm.qa_type = 'single_hop'
    }
    qaFormVisible.value = true
}

const saveQA = async () => {
    try {
        if (isEditQA.value) {
            await api.put(`/knowledge-bases/qa-pairs/${currentQAId.value}`, qaForm)
        } else {
            await api.post(`/knowledge-bases/documents/${currentDocId.value}/qa-pairs`, qaForm)
        }
        qaFormVisible.value = false
        // Refresh list
        const res = await api.get(`/knowledge-bases/documents/${currentDocId.value}/qa-pairs`)
        qaPairs.value = res.data
        ElMessage.success('保存成功')
    } catch (e) {
        ElMessage.error('操作失败')
    }
}

const deleteQA = async (id) => {
    if (!(await confirmAction('确定要删除该 QA 对吗？', '警告'))) return
    try {
        await api.delete(`/knowledge-bases/qa-pairs/${id}`)
        // Refresh list
        const res = await api.get(`/knowledge-bases/documents/${currentDocId.value}/qa-pairs`)
        qaPairs.value = res.data
        ElMessage.success('删除成功')
    } catch (e) {
        ElMessage.error('删除失败')
    }
}

const downloadQA = async (docId) => {
    try {
        // We need to handle blob download
        const response = await api.get(`/knowledge-bases/documents/${docId}/qa-pairs/download`, {
            responseType: 'blob'
        })
        const url = window.URL.createObjectURL(new Blob([response.data]))
        const link = document.createElement('a')
        link.href = url
        // Try to get filename from headers if possible, or generate one
        link.setAttribute('download', `qa_pairs_${docId}.md`)
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
    } catch (e) {
        ElMessage.error('下载失败')
    }
}

const viewChunks = async (row) => {
  try {
    const res = await api.get(`/knowledge-bases/documents/${row.id}/chunks`)
    chunks.value = res.data
    chunksVisible.value = true
  } catch (e) {
    ElMessage.error('加载分片失败')
  }
}

const previewFile = async (row) => {
    try {
        currentPreviewFile.value = row
        console.log('Requesting preview for:', row.id)
        const res = await api.get(`/knowledge-bases/documents/${row.id}/preview`, { responseType: 'blob' })
        const blob = new Blob([res.data], { type: res.headers['content-type'] })
        previewUrl.value = URL.createObjectURL(blob)
        previewVisible.value = true
    } catch (e) {
        console.error('Preview error:', e)
        const msg = e.response?.data?.detail || '文件可能不存在于服务器'
        ElMessage.error(`预览失败：${msg}`)
    }
}

const openReprocessDialog = (row) => {
    currentDocId.value = row.id
    // Try to get existing config from row or KB default
    // Since we don't have doc config in row (unless we added it to serializer), we use defaults
    // But we can check kb.chunking_config
    if (kb.value.chunking_config) {
        reprocessForm.strategy = kb.value.chunking_config.method || 'recursive'
        reprocessForm.chunk_size = kb.value.chunking_config.chunk_size || 1000
        reprocessForm.chunk_overlap = kb.value.chunking_config.chunk_overlap || 200
        reprocessForm.separator = kb.value.chunking_config.separator || ''
    } else {
        reprocessForm.strategy = 'recursive'
        reprocessForm.chunk_size = 1000
        reprocessForm.chunk_overlap = 200
        reprocessForm.separator = ''
    }
    reprocessVisible.value = true
}

const startReprocess = async () => {
    try {
        isProcessing.value = true
        processingStatus.value = '正在重新处理...'
        processingPercentage.value = 0
        
        await api.post(`/knowledge-bases/documents/${currentDocId.value}/reprocess`, reprocessForm)
        
        reprocessVisible.value = false
        // Polling will handle progress update via document status
        // But for better UX, we can simulate or poll specifically
        
        // Let's rely on the global poller but show the dialog
        // Actually, reprocess API returns immediately. 
        // We need to poll until status is 2 (Completed) or 3 (Failed)
        
        const pollId = setInterval(async () => {
            try {
                // We need an endpoint to get single doc status or refresh list
                // Better to fetch list to update status
                await fetchDocuments()
                const doc = documents.value.find(d => d.id === currentDocId.value)
                
                if (doc) {
                    if (doc.status === 1) { // Processing
                        processingPercentage.value = (processingPercentage.value + 10) % 90
                    } else if (doc.status === 2) { // Success
                        processingPercentage.value = 100
                        processingStatus.value = '已完成'
                        clearInterval(pollId)
                        setTimeout(() => { isProcessing.value = false }, 1000)
                    } else if (doc.status === 3) { // Failed
                        processingStatus.value = '失败'
                        clearInterval(pollId)
                        setTimeout(() => { isProcessing.value = false }, 2000)
                    }
                }
            } catch (e) {
                clearInterval(pollId)
                isProcessing.value = false
            }
        }, 1000)
        
    } catch (e) {
        ElMessage.error('重新处理失败')
        isProcessing.value = false
    }
}

const getStatusType = getNumericStatusType
const getStatusText = getDocStatusText

onMounted(() => {
  fetchKB()
  fetchDocuments()
  startPolling()
})
</script>

<style scoped>
.kb-detail {
  padding: 20px;
}
.header {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 20px;
}
.desc {
  color: #666;
  font-size: 0.9em;
}
.actions-bar {
  margin-bottom: 20px;
  display: flex;
  gap: 10px;
  align-items: center;
}
</style>
