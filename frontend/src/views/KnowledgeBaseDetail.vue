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
        :action="`/api/v1/knowledge-bases/${kbId}/upload`"
        :headers="headers"
        multiple
        :on-success="handleUploadSuccess"
        :on-error="handleUploadError"
        :on-progress="handleUploadProgress"
        :file-list="fileList"
        :show-file-list="false"
        style="display: inline-block; margin-right: 10px;"
      >
        <el-button type="primary" icon="Upload">Batch Upload</el-button>
      </el-upload>
      
      <el-button type="warning" @click="batchRetry" :disabled="!selectedDocs.length" icon="Refresh">Batch Retry</el-button>
      <el-button type="danger" @click="batchDelete" :disabled="!selectedDocs.length" icon="Delete">Batch Delete</el-button>
      <el-button @click="fetchDocuments" icon="RefreshRight">Refresh List</el-button>
    </div>

    <!-- Upload Queue Monitor -->
    <el-collapse v-if="uploadQueue.length > 0" v-model="activeNames" style="margin-bottom: 20px;">
      <el-collapse-item title="Upload Queue" name="1">
        <el-table :data="uploadQueue" style="width: 100%" size="small">
          <el-table-column prop="name" label="File Name" />
          <el-table-column label="Progress" width="300">
            <template #default="scope">
              <el-progress :percentage="scope.row.percentage" :status="scope.row.status === 'success' ? 'success' : (scope.row.status === 'fail' ? 'exception' : '')" />
            </template>
          </el-table-column>
          <el-table-column prop="status" label="Status" width="100" />
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
      <el-table-column prop="filename" label="Filename" min-width="200" />
      <el-table-column prop="file_size" label="Size">
        <template #default="scope">
          {{ scope.row.file_size ? (scope.row.file_size / 1024).toFixed(2) + ' KB' : 'Unknown' }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="Status" width="120">
        <template #default="scope">
          <el-tag :type="getStatusType(scope.row.status)">
            {{ getStatusText(scope.row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="Chunks" width="100" />
      <el-table-column prop="created_at" label="Upload Time">
        <template #default="scope">
          {{ new Date(scope.row.created_at.endsWith('Z') ? scope.row.created_at : scope.row.created_at + 'Z').toLocaleString() }}
        </template>
      </el-table-column>
      <el-table-column label="Actions" width="250" fixed="right">
        <template #default="scope">
          <el-button size="small" @click="generateQA(scope.row)">Gen QA</el-button>
          <el-button size="small" @click="viewQA(scope.row)">Manage QA</el-button>
          <el-button size="small" @click="viewChunks(scope.row)">Chunks</el-button>
          <el-button size="small" @click="previewFile(scope.row)">Preview</el-button>
          <el-button size="small" type="primary" @click="openReprocessDialog(scope.row)">Re-chunk</el-button>
          <el-button size="small" type="warning" @click="retryDoc(scope.row)" v-if="scope.row.status === 3">Retry</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Preview Dialog -->
    <el-dialog v-model="previewVisible" title="File Preview" width="80%" top="5vh" class="preview-dialog">
        <div class="preview-header">
            <h3>{{ currentPreviewFile?.filename }}</h3>
        </div>
        <div class="preview-content">
            <iframe :src="previewUrl" style="width: 100%; height: 80vh; border: none;"></iframe>
        </div>
    </el-dialog>

    <!-- Reprocess Dialog -->
    <el-dialog v-model="reprocessVisible" title="Reprocess Document" width="30%">
        <el-form :model="reprocessForm" label-width="120px">
            <el-form-item label="Strategy">
                <el-select v-model="reprocessForm.strategy">
                    <el-option label="Recursive" value="recursive" />
                    <el-option label="Fixed Size" value="fixed" />
                    <el-option label="Separator" value="separator" />
                    <el-option label="Semantic" value="semantic" />
                </el-select>
            </el-form-item>
            <el-form-item label="Chunk Size">
                <el-input-number v-model="reprocessForm.chunk_size" :min="100" :max="2000" :step="100" />
            </el-form-item>
            <el-form-item label="Overlap">
                <el-input-number v-model="reprocessForm.chunk_overlap" :min="0" :max="500" :step="10" />
            </el-form-item>
            <el-form-item label="Separator" v-if="reprocessForm.strategy === 'separator'">
                <el-input v-model="reprocessForm.separator" placeholder="\n\n" />
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="reprocessVisible = false">Cancel</el-button>
            <el-button type="primary" @click="startReprocess" :loading="isProcessing">Start</el-button>
        </template>
    </el-dialog>

    <!-- Progress Dialog for Long Running Tasks -->
    <el-dialog v-model="isProcessing" :title="processingStatus" width="30%" :close-on-click-modal="false" :show-close="false">
        <el-progress :percentage="processingPercentage" :status="processingPercentage === 100 ? 'success' : ''" />
        <div style="margin-top: 10px; text-align: center;">Please wait...</div>
    </el-dialog>

    <!-- QA Dialog -->
    <el-dialog v-model="qaVisible" title="Manage QA Pairs" width="80%">
      <div style="margin-bottom: 10px; display: flex; justify-content: space-between;">
        <el-button type="primary" @click="openQAForm()">Add QA Pair</el-button>
        <el-button type="success" @click="downloadQA(currentDocId)">Download MD</el-button>
      </div>
      <el-table :data="qaPairs" height="400">
        <el-table-column prop="question" label="Question" min-width="200" />
        <el-table-column prop="answer" label="Answer" min-width="200" />
        <el-table-column prop="qa_type" label="Type" width="120">
             <template #default="scope">
                 <el-tag>{{ scope.row.qa_type }}</el-tag>
             </template>
        </el-table-column>
        <el-table-column label="Actions" width="150">
            <template #default="scope">
                <el-button size="small" @click="openQAForm(scope.row)">Edit</el-button>
                <el-button size="small" type="danger" @click="deleteQA(scope.row.id)">Delete</el-button>
            </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- QA Form Dialog -->
    <el-dialog v-model="qaFormVisible" :title="isEditQA ? 'Edit QA Pair' : 'Add QA Pair'" width="50%">
        <el-form :model="qaForm" label-width="100px">
            <el-form-item label="Type">
                <el-select v-model="qaForm.qa_type" allow-create filterable default-first-option placeholder="Select or type tag">
                    <el-option label="Single Hop" value="single_hop" />
                    <el-option label="Multi Hop" value="multi_hop" />
                    <el-option label="Summary" value="summary" />
                    <el-option label="General" value="general" />
                </el-select>
            </el-form-item>
            <el-form-item label="Question">
                <el-input v-model="qaForm.question" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="Answer">
                <el-input v-model="qaForm.answer" type="textarea" :rows="4" />
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="qaFormVisible = false">Cancel</el-button>
            <el-button type="primary" @click="saveQA">Save</el-button>
        </template>
    </el-dialog>

    <!-- Chunks Dialog -->
    <el-dialog v-model="chunksVisible" title="Document Chunks" width="70%">
      <el-table :data="chunks" height="400">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="content" label="Content" />
        <el-table-column prop="page_num" label="Page" width="80" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, onUnmounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api'
import { Back, Upload, Refresh, Delete, RefreshRight, View, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

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
    ElMessage.error('Failed to load KB details')
    router.push('/knowledge-bases')
  }
}

const fetchDocuments = async () => {
  loading.value = true
  try {
    const res = await api.get(`/knowledge-bases/${kbId}/documents`)
    documents.value = res.data
  } catch (e) {
    ElMessage.error('Failed to load documents')
  } finally {
    loading.value = false
  }
}

// Polling for document status updates (Processing Queue Monitor)
let pollInterval = null
const startPolling = () => {
  pollInterval = setInterval(async () => {
    // Only poll if there are documents in processing state (1) or uploading (0)
    const pendingDocs = documents.value.some(d => d.status === 0 || d.status === 1)
    if (pendingDocs || uploadQueue.value.length > 0) {
        // Silent refresh
        try {
            const res = await api.get(`/knowledge-bases/${kbId}/documents`)
            documents.value = res.data
        } catch (e) {}
    }
  }, 3000)
}

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
})

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
  ElMessage.success(`File ${file.name} uploaded successfully`)
  fetchDocuments()
}

const handleUploadError = (err, file, fileList) => {
  const existing = uploadQueue.value.find(f => f.uid === file.uid)
  if (existing) {
    existing.status = 'fail'
    existing.percentage = 0
  }
  ElMessage.error(`File ${file.name} upload failed`)
}

const handleSelectionChange = (val) => {
  selectedDocs.value = val
}

const batchRetry = async () => {
  try {
    const ids = selectedDocs.value.map(d => d.id)
    await api.post('/knowledge-bases/documents/batch-retry', ids)
    ElMessage.success('Batch retry started')
    fetchDocuments()
  } catch (e) {
    ElMessage.error('Batch retry failed')
  }
}

const batchDelete = async () => {
  try {
    await ElMessageBox.confirm('Are you sure you want to delete selected documents?', 'Warning', {
      type: 'warning'
    })
    const ids = selectedDocs.value.map(d => d.id)
    await api.delete('/knowledge-bases/documents/batch-delete', { data: ids })
    ElMessage.success('Documents deleted')
    fetchDocuments()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('Delete failed')
  }
}

const retryDoc = async (row) => {
  try {
    await api.post(`/knowledge-bases/documents/${row.id}/retry`)
    ElMessage.success('Retry started')
    fetchDocuments()
  } catch (e) {
    ElMessage.error('Retry failed')
  }
}

const generateQA = async (row) => {
    try {
        ElMessageBox.prompt('How many QA pairs to generate?', 'Generate QA', {
            confirmButtonText: 'Generate',
            cancelButtonText: 'Cancel',
            inputPattern: /^[1-9]\d*$/,
            inputErrorMessage: 'Invalid Number',
            inputValue: row.chunk_count > 0 ? row.chunk_count : 5
        }).then(async ({ value }) => {
            isProcessing.value = true
            processingStatus.value = 'Generating QA...'
            processingPercentage.value = 0
            
            const progressTimer = setInterval(() => {
                if (processingPercentage.value < 90) {
                    processingPercentage.value += 5
                }
            }, 500)
            
            await api.post(`/knowledge-bases/documents/${row.id}/generate-qa`, null, { params: { num_pairs: value } })
            
            clearInterval(progressTimer)
            processingPercentage.value = 100
            processingStatus.value = 'Completed'
            ElMessage.success('QA Generation completed')
            
            setTimeout(() => { isProcessing.value = false }, 1000)
        }).catch(() => {
             // Catch cancel
        })
    } catch (e) {
        if (e !== 'cancel') {
            ElMessage.error('QA Generation failed')
            isProcessing.value = false
        }
    }
}

const viewQA = async (row) => {
  currentDocId.value = row.id
  try {
    const res = await api.get(`/knowledge-bases/documents/${row.id}/qa-pairs`)
    qaPairs.value = res.data
    qaVisible.value = true
  } catch (e) {
    ElMessage.error('Failed to load QA pairs')
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
        ElMessage.success('Saved')
    } catch (e) {
        ElMessage.error('Operation failed')
    }
}

const deleteQA = async (id) => {
    try {
        await ElMessageBox.confirm('Delete this QA pair?', 'Warning', { type: 'warning' })
        await api.delete(`/knowledge-bases/qa-pairs/${id}`)
        // Refresh list
        const res = await api.get(`/knowledge-bases/documents/${currentDocId.value}/qa-pairs`)
        qaPairs.value = res.data
        ElMessage.success('Deleted')
    } catch (e) {
        if (e !== 'cancel') ElMessage.error('Delete failed')
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
        ElMessage.error('Download failed')
    }
}

const viewChunks = async (row) => {
  try {
    const res = await api.get(`/knowledge-bases/documents/${row.id}/chunks`)
    chunks.value = res.data
    chunksVisible.value = true
  } catch (e) {
    ElMessage.error('Failed to load chunks')
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
        const msg = e.response?.data?.detail || 'File might not exist on server'
        ElMessage.error(`Preview failed: ${msg}`)
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
        processingStatus.value = 'Reprocessing...'
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
                        processingStatus.value = 'Completed'
                        clearInterval(pollId)
                        setTimeout(() => { isProcessing.value = false }, 1000)
                    } else if (doc.status === 3) { // Failed
                        processingStatus.value = 'Failed'
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
        ElMessage.error('Reprocess failed')
        isProcessing.value = false
    }
}

const getStatusType = (status) => {
    const map = {0: 'info', 1: 'warning', 2: 'success', 3: 'danger'}
    return map[status] || 'info'
}

const getStatusText = (status) => {
    const map = {0: 'Uploading', 1: 'Processing', 2: 'Completed', 3: 'Failed'}
    return map[status] || 'Unknown'
}

const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleString()
}

const formatSize = (bytes) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

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
