<template>
  <div class="evaluation-container">
    <h2>评测</h2>
    
    <el-tabs v-model="activeTab" type="border-card">
      <!-- Configuration Tab -->
      <el-tab-pane label="新建评测" name="config">
        <el-form :model="form" label-width="150px" style="max-width: 800px;">
          <el-form-item label="评测模式">
            <el-radio-group v-model="form.mode">
              <el-radio value="kb">知识库级别</el-radio>
              <el-radio value="doc">文档级别</el-radio>
            </el-radio-group>
          </el-form-item>
          
          <el-form-item label="自定义数据集">
              <el-switch v-model="form.is_custom_upload" active-text="上传文件" inactive-text="自动生成" />
          </el-form-item>
          
          <div v-if="form.is_custom_upload">
              <el-form-item label="上传文件">
                  <el-upload
                    class="upload-demo"
                    action="#"
                    :auto-upload="false"
                    :on-change="handleFileChange"
                    :limit="1"
                    accept=".json,.csv,.xlsx"
                  >
                    <template #trigger>
                      <el-button type="primary">选择文件</el-button>
                    </template>
                    <template #tip>
                      <div class="el-upload__tip">
                        支持 JSON/CSV/Excel。格式：question、answer（或 ground_truth）、type（可选）
                      </div>
                    </template>
                  </el-upload>
              </el-form-item>
          </div>
          <div v-else>
              <el-form-item label="知识库">
                <el-select v-model="form.kb_id" placeholder="选择知识库" @change="onKBChange" style="width: 100%;">
                  <el-option
                    v-for="item in kbs"
                    :key="item.id"
                    :label="item.name"
                    :value="item.id"
                  />
                </el-select>
              </el-form-item>
              
              <el-form-item label="文档" v-if="form.mode === 'doc'">
                <el-select v-model="form.doc_ids" multiple placeholder="选择文档" style="width: 100%;">
                  <el-option
                    v-for="doc in documents"
                    :key="doc.id"
                    :label="doc.filename"
                    :value="doc.id"
                  />
                </el-select>
              </el-form-item>
              
              <el-form-item label="采样文档数（N）" v-if="form.mode === 'kb'">
                <el-input-number v-model="form.num_docs" :min="1" :max="50" />
                <span class="hint">从知识库中随机选择 N 篇文档</span>
              </el-form-item>
              
              <el-form-item label="总题数（M）">
                <el-input-number v-model="form.num_questions" :min="5" :max="2000" :step="10" />
              </el-form-item>
              
              <el-divider content-position="left">题型分布比例</el-divider>
              
              <el-form-item label="单跳">
                 <el-slider v-model="form.ratios.single_hop" :min="0" :max="1" :step="0.1" show-input />
              </el-form-item>
              <el-form-item label="多跳">
                 <el-slider v-model="form.ratios.multi_hop" :min="0" :max="1" :step="0.1" show-input />
              </el-form-item>
              <el-form-item label="错误/否定">
                 <el-slider v-model="form.ratios.error" :min="0" :max="1" :step="0.1" show-input />
              </el-form-item>
              
              <el-alert
                v-if="totalRatio !== 1"
                title="警告：比例之和应为 1.0"
                type="warning"
                show-icon
                :closable="false"
                style="margin-bottom: 20px;"
              />
          </div>
          
          <el-form-item>
            <el-button type="primary" @click="startGeneration" :loading="loading" :disabled="!isFormValid">
                {{ form.is_custom_upload ? '上传并创建任务' : '生成数据集' }}
            </el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>
      
      <!-- History Tab -->
      <el-tab-pane label="历史与报告" name="history">
        <div style="margin-bottom: 10px; display: flex;">
            <el-button @click="fetchTasks" icon="Refresh" circle></el-button>
            <div style="flex: 1"></div>
            <el-button type="danger" @click="batchDeleteTasks" :disabled="!selectedTasks.length">批量删除</el-button>
        </div>
        <el-table :data="tasks" stripe style="width: 100%" @selection-change="handleSelectionChange" row-key="id">
            <el-table-column type="selection" width="55" :reserve-selection="true" />
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="name" label="任务名称" min-width="180" />
            <el-table-column label="类型" width="100">
                <template #default="scope">
                    <el-tag v-if="scope.row.is_custom_dataset" type="info">自定义</el-tag>
                    <el-tag v-else>自动</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="进度" width="200">
                <template #default="scope">
                    <div v-if="scope.row.status === 4">
                        <el-tag type="success">数据集就绪</el-tag>
                        <small style="margin-left: 5px;">{{ scope.row.total_count }} 条</small>
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
            <el-table-column prop="created_at" label="创建时间" width="180">
                <template #default="scope">
                    {{ formatDate(scope.row.created_at) }}
                </template>
            </el-table-column>
            <el-table-column label="操作" width="250" fixed="right">
                <template #default="scope">
                    <el-button size="small" @click="viewDataset(scope.row)">数据集</el-button>
                    <el-button size="small" type="success" v-if="scope.row.status === 4" @click="runEvaluation(scope.row)">运行</el-button>
                    <el-button size="small" type="primary" v-if="scope.row.status === 2 || scope.row.status === 3" @click="viewReport(scope.row)">报告</el-button>
                </template>
            </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- Dataset Dialog -->
    <el-dialog v-model="datasetVisible" title="评测数据集" width="80%">
        <el-table :data="datasetItems" border style="width: 100%" max-height="500">
            <el-table-column prop="question" label="问题">
                <template #default="scope">
                    <el-input v-if="editingRow === scope.row.id" v-model="editingData.question" type="textarea" />
                    <span v-else>{{ scope.row.question }}</span>
                </template>
            </el-table-column>
            <el-table-column prop="ground_truth" label="标准答案">
                <template #default="scope">
                    <el-input v-if="editingRow === scope.row.id" v-model="editingData.ground_truth" type="textarea" />
                    <span v-else>{{ scope.row.ground_truth }}</span>
                </template>
            </el-table-column>
            <el-table-column prop="qa_type" label="类型" width="120">
                <template #default="scope">
                    <el-select v-if="editingRow === scope.row.id" v-model="editingData.qa_type">
                        <el-option label="单跳" value="single_hop" />
                        <el-option label="多跳" value="multi_hop" />
                        <el-option label="错误" value="error" />
                    </el-select>
                    <el-tag v-else>{{ scope.row.qa_type }}</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="操作" width="150">
                <template #default="scope">
                    <div v-if="editingRow === scope.row.id">
                        <el-button size="small" type="success" @click="saveEdit(scope.row)">保存</el-button>
                        <el-button size="small" @click="cancelEdit">取消</el-button>
                    </div>
                    <div v-else>
                        <el-button size="small" type="primary" @click="startEdit(scope.row)" :disabled="currentTaskStatus !== 4">编辑</el-button>
                        <el-button size="small" type="danger" @click="deleteItem(scope.row)" :disabled="currentTaskStatus !== 4">删除</el-button>
                    </div>
                </template>
            </el-table-column>
        </el-table>
        <template #footer>
            <el-button @click="datasetVisible = false">关闭</el-button>
            <el-button type="primary" v-if="currentTaskStatus === 4" @click="confirmAndRun">确认并运行评测</el-button>
        </template>
    </el-dialog>

    <!-- Report Dialog -->
    <el-dialog v-model="reportVisible" title="评测报告" width="70%" top="5vh">
        <div class="report-content">
            <pre>{{ reportContent }}</pre>
        </div>
        <template #footer>
            <el-button @click="reportVisible = false">关闭</el-button>
            <el-button type="primary" @click="downloadReport">下载报告</el-button>
        </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import api from '../api'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { getNumericStatusType, getEvalStatusText } from '../utils/status'
import { formatDate } from '../utils/format'
import { usePolling, POLL_SLOW } from '../composables/usePolling'
import { confirmAction } from '../utils/confirm'

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
            ElMessage.success('自定义数据集已上传，可预览并运行评测')
            fetchTasks()
        } else {
            await api.post('/evaluations/generate', form)
            ElMessage.success('数据集生成已开始，请稍候...')
            fetchTasks()
        }
        activeTab.value = 'history'
    } catch (e) {
        ElMessage.error(e.response?.data?.detail || '启动生成失败')
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
        ElMessage.error('加载数据集失败')
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
        ElMessage.success('更新成功')
    } catch (e) {
        ElMessage.error('更新失败')
    }
}

const deleteItem = async (row) => {
    if (!(await confirmAction('确定删除该条数据吗？'))) return
    try {
        await api.delete(`/evaluations/dataset-items/${row.id}`)
        datasetItems.value = datasetItems.value.filter(i => i.id !== row.id)
        ElMessage.success('删除成功')
    } catch (e) {
        ElMessage.error('删除失败')
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
        ElMessage.success('评测已开始')
        fetchTasks()
    } catch (e) {
        ElMessage.error('启动评测失败')
    }
}

const batchDeleteTasks = async () => {
    if (!(await confirmAction(`确定删除 ${selectedTasks.value.length} 个任务吗？`, '警告'))) return
    try {
        const ids = selectedTasks.value.map(t => t.id)
        await api.delete('/evaluations/tasks/batch-delete', { data: ids })
        ElMessage.success('任务已删除')
        fetchTasks()
        selectedTasks.value = []
    } catch (e) {
        ElMessage.error('删除任务失败：' + (e.response?.data?.detail || e.message))
    }
}

const fetchKBs = async () => {
    try {
        const res = await api.get('/knowledge-bases/')
        kbs.value = res.data
    } catch (e) {
        ElMessage.error('加载知识库失败')
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
            ElMessage.error('加载文档失败')
        }
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
        ElMessage.error('加载报告失败')
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

const statusText = getEvalStatusText
const statusType = getNumericStatusType


const { start: startPolling } = usePolling(() => {
    if (activeTab.value === 'history') {
        fetchTasks()
    }
}, POLL_SLOW)

onMounted(() => {
    fetchKBs()
    fetchTasks()
    startPolling()
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
