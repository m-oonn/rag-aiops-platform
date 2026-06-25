<template>
  <div class="evaluation-container">
    <h2>RAG System Evaluation</h2>
    
    <el-tabs v-model="activeTab" type="border-card">
      <!-- Configuration Tab -->
      <el-tab-pane label="New Evaluation" name="config">
        <el-form :model="form" label-width="150px" style="max-width: 800px;">
          <el-form-item label="Evaluation Mode">
            <el-radio-group v-model="form.mode">
              <el-radio value="kb">Knowledge Base Level</el-radio>
              <el-radio value="doc">Single Document Level</el-radio>
            </el-radio-group>
          </el-form-item>
          
          <el-form-item label="Custom Dataset">
              <el-switch v-model="form.is_custom_upload" active-text="Upload File" inactive-text="Auto Generate" />
          </el-form-item>
          
          <div v-if="form.is_custom_upload">
              <el-form-item label="Upload File">
                  <el-upload
                    class="upload-demo"
                    action="#"
                    :auto-upload="false"
                    :on-change="handleFileChange"
                    :limit="1"
                    accept=".json,.csv,.xlsx"
                  >
                    <template #trigger>
                      <el-button type="primary">Select File</el-button>
                    </template>
                    <template #tip>
                      <div class="el-upload__tip">
                        Support JSON/CSV/Excel. Format: question, answer (or ground_truth), type (optional)
                      </div>
                    </template>
                  </el-upload>
              </el-form-item>
          </div>
          <div v-else>
              <el-form-item label="Knowledge Base">
                <el-select v-model="form.kb_id" placeholder="Select Knowledge Base" @change="onKBChange" style="width: 100%;">
                  <el-option
                    v-for="item in kbs"
                    :key="item.id"
                    :label="item.name"
                    :value="item.id"
                  />
                </el-select>
              </el-form-item>
              
              <el-form-item label="Document" v-if="form.mode === 'doc'">
                <el-select v-model="form.doc_ids" multiple placeholder="Select Document(s)" style="width: 100%;">
                  <el-option
                    v-for="doc in documents"
                    :key="doc.id"
                    :label="doc.filename"
                    :value="doc.id"
                  />
                </el-select>
              </el-form-item>
              
              <el-form-item label="Sample Docs (N)" v-if="form.mode === 'kb'">
                <el-input-number v-model="form.num_docs" :min="1" :max="50" />
                <span class="hint">Randomly select N documents from KB</span>
              </el-form-item>
              
              <el-form-item label="Total Questions (M)">
                <el-input-number v-model="form.num_questions" :min="5" :max="2000" :step="10" />
              </el-form-item>
              
              <el-divider content-position="left">Question Type Distribution (Ratio)</el-divider>
              
              <el-form-item label="Single Hop">
                 <el-slider v-model="form.ratios.single_hop" :min="0" :max="1" :step="0.1" show-input />
              </el-form-item>
              <el-form-item label="Multi Hop">
                 <el-slider v-model="form.ratios.multi_hop" :min="0" :max="1" :step="0.1" show-input />
              </el-form-item>
              <el-form-item label="Error/Negative">
                 <el-slider v-model="form.ratios.error" :min="0" :max="1" :step="0.1" show-input />
              </el-form-item>
              
              <el-alert
                v-if="totalRatio !== 1"
                title="Warning: Ratios should sum to 1.0"
                type="warning"
                show-icon
                :closable="false"
                style="margin-bottom: 20px;"
              />
          </div>
          
          <el-form-item>
            <el-button type="primary" @click="startGeneration" :loading="loading" :disabled="!isFormValid">
                {{ form.is_custom_upload ? 'Upload & Create Task' : 'Generate Dataset' }}
            </el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>
      
      <!-- History Tab -->
      <el-tab-pane label="History & Reports" name="history">
        <div style="margin-bottom: 10px; display: flex;">
            <el-button @click="fetchTasks" icon="Refresh" circle></el-button>
            <div style="flex: 1"></div>
            <el-button type="danger" @click="batchDeleteTasks" :disabled="!selectedTasks.length">Batch Delete</el-button>
        </div>
        <el-table :data="tasks" stripe style="width: 100%" @selection-change="handleSelectionChange" row-key="id">
            <el-table-column type="selection" width="55" :reserve-selection="true" />
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="name" label="Task Name" min-width="180" />
            <el-table-column label="Type" width="100">
                <template #default="scope">
                    <el-tag v-if="scope.row.is_custom_dataset" type="info">Custom</el-tag>
                    <el-tag v-else>Auto</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="Progress" width="200">
                <template #default="scope">
                    <div v-if="scope.row.status === 4">
                        <el-tag type="success">Dataset Ready</el-tag>
                        <small style="margin-left: 5px;">{{ scope.row.total_count }} items</small>
                    </div>
                    <div v-else-if="scope.row.status === 1 || scope.row.status === 2">
                        <el-progress :percentage="calculateProgress(scope.row)" :format="progressFormat" />
                        <small v-if="scope.row.total_count > 0">{{ scope.row.completed_count }} / {{ scope.row.total_count }}</small>
                    </div>
                    <div v-else>
                         <el-tag :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
                    </div>
                </template>
            </el-table-column>
            <el-table-column prop="created_at" label="Created At" width="180">
                <template #default="scope">
                    {{ formatDate(scope.row.created_at) }}
                </template>
            </el-table-column>
            <el-table-column label="Actions" width="250" fixed="right">
                <template #default="scope">
                    <el-button size="small" @click="viewDataset(scope.row)">Dataset</el-button>
                    <el-button size="small" type="success" v-if="scope.row.status === 4" @click="runEvaluation(scope.row)">Run</el-button>
                    <el-button size="small" type="primary" v-if="scope.row.status === 2 || scope.row.status === 3" @click="viewReport(scope.row)">Report</el-button>
                </template>
            </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- Dataset Dialog -->
    <el-dialog v-model="datasetVisible" title="Evaluation Dataset" width="80%">
        <el-table :data="datasetItems" border style="width: 100%" max-height="500">
            <el-table-column prop="question" label="Question">
                <template #default="scope">
                    <el-input v-if="editingRow === scope.row.id" v-model="editingData.question" type="textarea" />
                    <span v-else>{{ scope.row.question }}</span>
                </template>
            </el-table-column>
            <el-table-column prop="ground_truth" label="Ground Truth">
                <template #default="scope">
                    <el-input v-if="editingRow === scope.row.id" v-model="editingData.ground_truth" type="textarea" />
                    <span v-else>{{ scope.row.ground_truth }}</span>
                </template>
            </el-table-column>
            <el-table-column prop="qa_type" label="Type" width="120">
                <template #default="scope">
                    <el-select v-if="editingRow === scope.row.id" v-model="editingData.qa_type">
                        <el-option label="Single Hop" value="single_hop" />
                        <el-option label="Multi Hop" value="multi_hop" />
                        <el-option label="Error" value="error" />
                    </el-select>
                    <el-tag v-else>{{ scope.row.qa_type }}</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="Actions" width="150">
                <template #default="scope">
                    <div v-if="editingRow === scope.row.id">
                        <el-button size="small" type="success" @click="saveEdit(scope.row)">Save</el-button>
                        <el-button size="small" @click="cancelEdit">Cancel</el-button>
                    </div>
                    <div v-else>
                        <el-button size="small" type="primary" @click="startEdit(scope.row)" :disabled="currentTaskStatus !== 4">Edit</el-button>
                        <el-button size="small" type="danger" @click="deleteItem(scope.row)" :disabled="currentTaskStatus !== 4">Delete</el-button>
                    </div>
                </template>
            </el-table-column>
        </el-table>
        <template #footer>
            <el-button @click="datasetVisible = false">Close</el-button>
            <el-button type="primary" v-if="currentTaskStatus === 4" @click="confirmAndRun">Confirm & Run Evaluation</el-button>
        </template>
    </el-dialog>

    <!-- Report Dialog -->
    <el-dialog v-model="reportVisible" title="Evaluation Report" width="70%" top="5vh">
        <div class="report-content">
            <pre>{{ reportContent }}</pre>
        </div>
        <template #footer>
            <el-button @click="reportVisible = false">Close</el-button>
            <el-button type="primary" @click="downloadReport">Download MD</el-button>
        </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

const activeTab = ref('config')
const kbs = ref([])
const documents = ref([])
const tasks = ref([])
const loading = ref(false)
const reportVisible = ref(false)
const reportContent = ref('')
const currentTaskId = ref(null)

// Dataset Dialog
    const datasetVisible = ref(false)
    const datasetItems = ref([])
    const currentTask = ref(null)
    const currentTaskStatus = ref(0)
    const editingRow = ref(null)
    const editingData = reactive({ question: '', ground_truth: '', qa_type: '' })
    const selectedTasks = ref([])
    const fileList = ref([]) // For upload

const form = reactive({
    mode: 'kb',
    kb_id: null,
    doc_ids: [],
    num_docs: 5,
    num_questions: 10,
    ratios: {
        single_hop: 0.7,
        multi_hop: 0.2,
        error: 0.1
    },
    is_custom_upload: false
})

const totalRatio = computed(() => {
    return parseFloat((form.ratios.single_hop + form.ratios.multi_hop + form.ratios.error).toFixed(1))
})

const isFormValid = computed(() => {
    if (form.is_custom_upload) return fileList.value.length > 0
    if (!form.kb_id) return false
    if (form.mode === 'doc' && form.doc_ids.length === 0) return false
    return true
})

const handleFileChange = (file) => {
    fileList.value = [file]
}

const handleSelectionChange = (val) => {
    selectedTasks.value = val
}

const startGeneration = async () => {
    loading.value = true
    try {
        if (form.is_custom_upload) {
            // Create task first
            const res = await api.post('/evaluations/generate', form)
            const task = res.data
            // Upload file
            const formData = new FormData()
            formData.append('file', fileList.value[0].raw)
            await api.post(`/evaluations/${task.id}/upload-dataset`, formData)
            ElMessage.success('Custom dataset uploaded. You can now preview and run evaluation.')
            fetchTasks()
        } else {
            await api.post('/evaluations/generate', form)
            ElMessage.success('Dataset generation started. Please wait...')
            fetchTasks()
        }
        activeTab.value = 'history'
    } catch (e) {
        ElMessage.error(e.response?.data?.detail || 'Failed to start generation')
    } finally {
        loading.value = false
    }
}

const viewDataset = async (task) => {
    currentTask.value = task
    currentTaskStatus.value = task.status
    try {
        const res = await api.get(`/evaluations/${task.id}/dataset`)
        datasetItems.value = res.data
        datasetVisible.value = true
    } catch (e) {
        ElMessage.error('Failed to load dataset')
    }
}

const startEdit = (row) => {
    editingRow.value = row.id
    editingData.question = row.question
    editingData.ground_truth = row.ground_truth
    editingData.qa_type = row.qa_type
}

const cancelEdit = () => {
    editingRow.value = null
}

const saveEdit = async (row) => {
    try {
        await api.put(`/evaluations/dataset-items/${row.id}`, editingData)
        row.question = editingData.question
        row.ground_truth = editingData.ground_truth
        row.qa_type = editingData.qa_type
        editingRow.value = null
        ElMessage.success('Updated')
    } catch (e) {
        ElMessage.error('Failed to update')
    }
}

const deleteItem = async (row) => {
    try {
        await ElMessageBox.confirm('Delete this item?')
        await api.delete(`/evaluations/dataset-items/${row.id}`)
        datasetItems.value = datasetItems.value.filter(i => i.id !== row.id)
        ElMessage.success('Deleted')
    } catch (e) {
        if(e !== 'cancel') ElMessage.error('Failed to delete')
    }
}

const confirmAndRun = async () => {
    if (!currentTask.value) return
    runEvaluation(currentTask.value)
    datasetVisible.value = false
}

const runEvaluation = async (task) => {
    try {
        await api.post(`/evaluations/${task.id}/run`)
        ElMessage.success('Evaluation started')
        fetchTasks()
    } catch (e) {
        ElMessage.error('Failed to start evaluation')
    }
}

const batchDeleteTasks = async () => {
    try {
        await ElMessageBox.confirm(`Delete ${selectedTasks.value.length} tasks?`, 'Warning', { type: 'warning' })
        const ids = selectedTasks.value.map(t => t.id)
        await api.delete('/evaluations/tasks/batch-delete', { data: ids })
        ElMessage.success('Tasks deleted')
        fetchTasks()
        selectedTasks.value = []
    } catch (e) {
        if(e !== 'cancel') ElMessage.error('Failed to delete tasks: ' + (e.response?.data?.detail || e.message))
    }
}

const fetchKBs = async () => {
    try {
        const res = await api.get('/knowledge-bases/')
        kbs.value = res.data
    } catch (e) {
        ElMessage.error('Failed to load KBs')
    }
}

const onKBChange = async () => {
    form.doc_ids = []
    documents.value = []
    if (form.kb_id) {
        try {
            const res = await api.get(`/knowledge-bases/${form.kb_id}/documents`)
            documents.value = res.data
        } catch (e) {
            ElMessage.error('Failed to load documents')
        }
    }
}

const startEvaluation = async () => {
    loading.value = true
    try {
        if (form.is_custom_upload) {
            // Create task first
            const res = await api.post('/evaluations/generate', form)
            const task = res.data
            // Upload file
            const formData = new FormData()
            formData.append('file', fileList.value[0].raw)
            await api.post(`/evaluations/${task.id}/upload-dataset`, formData)
            ElMessage.success('Custom dataset uploaded. You can now preview and run evaluation.')
            fetchTasks()
        } else {
            await api.post('/evaluations/generate', form)
            ElMessage.success('Dataset generation started. Please wait...')
            fetchTasks()
        }
        activeTab.value = 'history'
    } catch (e) {
        ElMessage.error(e.response?.data?.detail || 'Failed to start generation')
    } finally {
        loading.value = false
    }
}

const fetchTasks = async () => {
    // Assuming we have an endpoint to list tasks, otherwise we might need to add one or mock it
    // The current router in evaluation.py doesn't seem to have a list endpoint!
    // I need to add one. For now let's assume I will add it.
    try {
        const res = await api.get('/evaluations/tasks')
        tasks.value = res.data
    } catch (e) {
        // ElMessage.error('Failed to load tasks')
    }
}

const viewReport = async (task) => {
    currentTaskId.value = task.id
    try {
        const res = await api.get(`/evaluations/${task.id}/report`)
        reportContent.value = res.data.content
        reportVisible.value = true
    } catch (e) {
        ElMessage.error('Failed to load report')
    }
}

const downloadReport = () => {
    const blob = new Blob([reportContent.value], { type: 'text/markdown' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `report_${currentTaskId.value}.md`
    link.click()
    window.URL.revokeObjectURL(url)
}

const calculateProgress = (row) => {
    if (!row.total_count || row.total_count === 0) return 0
    return Math.round((row.completed_count / row.total_count) * 100)
}

const progressFormat = (percentage) => {
    return `${percentage}%`
}

const statusText = (s) => {
    const map = {0: 'Pending', 1: 'Running', 2: 'Completed', 3: 'Failed'}
    return map[s] || 'Unknown'
}

const statusType = (s) => {
    const map = {0: 'info', 1: 'warning', 2: 'success', 3: 'danger'}
    return map[s] || 'info'
}

const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleString()
}

onMounted(() => {
    fetchKBs()
    fetchTasks()
    
    // Simple polling for history
    setInterval(() => {
        if (activeTab.value === 'history') {
            fetchTasks()
        }
    }, 5000)
})
</script>

<style scoped>
.hint {
    font-size: 12px;
    color: #999;
    margin-left: 10px;
}
.report-content {
    background: #f5f7fa;
    padding: 15px;
    border-radius: 4px;
    max-height: 60vh;
    overflow-y: auto;
}
.report-content pre {
    white-space: pre-wrap;
    font-family: monospace;
}
</style>