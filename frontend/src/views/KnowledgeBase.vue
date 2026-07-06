<template>
  <div>
    <h2>知识库</h2>
    <div class="header-actions">
        <el-button type="primary" @click="dialogVisible = true">创建知识库</el-button>
    </div>
    
    <div class="kb-grid">
      <el-card 
        v-for="kb in kbs" 
        :key="kb.id" 
        class="kb-card" 
        shadow="hover"
        @click="goToDetail(kb.id)"
      >
        <div class="kb-card-header">
            <el-icon class="kb-icon"><Folder /></el-icon>
        </div>
        <div class="kb-card-body">
            <h3>{{ kb.name }}</h3>
            <el-tooltip 
                class="box-item" 
                effect="dark" 
                :content="kb.description || '暂无描述'" 
                placement="top"
            >
                <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
            </el-tooltip>
        </div>
        <div class="kb-card-footer">
            <span>{{ formatDate(kb.created_at) }}</span>
            <div class="actions">
                <el-button 
                    type="primary" 
                    circle 
                    size="small" 
                    @click.stop="openEditDialog(kb)"
                    icon="Edit"
                />
                <el-button 
                    type="danger" 
                    circle 
                    size="small" 
                    @click.stop="deleteKB(kb.id)"
                    icon="Delete"
                />
            </div>
        </div>
      </el-card>
    </div>

    <!-- Create KB Dialog -->
    <el-dialog v-model="dialogVisible" title="创建知识库">
      <el-form :model="form" label-width="120px">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" />
        </el-form-item>
        
        <el-divider>分块策略</el-divider>
        <el-form-item label="切分方式">
            <el-select v-model="form.chunking_config.method">
                <el-option label="递归切分（推荐）" value="recursive" />
                <el-option label="固定长度" value="fixed" />
                <el-option label="分隔符" value="separator" />
                <el-option label="语义切分" value="semantic" />
            </el-select>
        </el-form-item>
        <el-form-item label="块大小">
            <el-input-number v-model="form.chunking_config.chunk_size" :min="100" :max="2000" :step="100" />
        </el-form-item>
        <el-form-item label="重叠长度">
            <el-input-number v-model="form.chunking_config.chunk_overlap" :min="0" :max="500" :step="10" />
        </el-form-item>
        <el-form-item label="分隔符" v-if="form.chunking_config.method === 'separator'">
            <el-input v-model="form.chunking_config.separator" placeholder="\n\n" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" @click="createKB">确定</el-button>
        </span>
      </template>
    </el-dialog>

    <!-- Edit KB Dialog -->
    <el-dialog v-model="editDialogVisible" title="编辑知识库">
      <el-form :model="editForm" label-width="120px">
        <el-form-item label="名称">
          <el-input v-model="editForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" />
        </el-form-item>
        
        <el-divider>分块策略</el-divider>
        <el-form-item label="切分方式">
            <el-select v-model="editForm.chunking_config.method">
                <el-option label="递归切分（推荐）" value="recursive" />
                <el-option label="固定长度" value="fixed" />
                <el-option label="分隔符" value="separator" />
                <el-option label="语义切分" value="semantic" />
            </el-select>
        </el-form-item>
        <el-form-item label="块大小">
            <el-input-number v-model="editForm.chunking_config.chunk_size" :min="100" :max="2000" :step="100" />
        </el-form-item>
        <el-form-item label="重叠长度">
            <el-input-number v-model="editForm.chunking_config.chunk_overlap" :min="0" :max="500" :step="10" />
        </el-form-item>
        <el-form-item label="分隔符" v-if="editForm.chunking_config.method === 'separator'">
            <el-input v-model="editForm.chunking_config.separator" placeholder="\n\n" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="editDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="updateKB">保存</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { Folder, Delete, Edit } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { formatDateOnly as formatDate } from '../utils/format'
import { confirmAction } from '../utils/confirm'

const router = useRouter()
const kbs = ref([])
const dialogVisible = ref(false)
const editDialogVisible = ref(false)
const currentKbId = ref(null)

const form = reactive({
  name: '',
  description: '',
  chunking_config: {
      method: 'recursive',
      chunk_size: 500,
      chunk_overlap: 50,
      separator: ''
  }
})

const editForm = reactive({
  name: '',
  description: '',
  chunking_config: {
      method: 'recursive',
      chunk_size: 500,
      chunk_overlap: 50,
      separator: ''
  }
})

const fetchKBs = async () => {
  const res = await api.get('/knowledge-bases/')
  kbs.value = res.data
}

const createKB = async () => {
  try {
      await api.post('/knowledge-bases/', form)
      dialogVisible.value = false
      fetchKBs()
      ElMessage.success('知识库创建成功')
  } catch (e) {
      ElMessage.error('创建知识库失败')
  }
}

const openEditDialog = (kb) => {
    currentKbId.value = kb.id
    editForm.name = kb.name
    editForm.description = kb.description
    // Deep copy to avoid reference issues
    editForm.chunking_config = JSON.parse(JSON.stringify(kb.chunking_config || {
        method: 'recursive',
        chunk_size: 500,
        chunk_overlap: 50,
        separator: ''
    }))
    editDialogVisible.value = true
}

const updateKB = async () => {
    try {
        await api.put(`/knowledge-bases/${currentKbId.value}`, editForm)
        editDialogVisible.value = false
        fetchKBs()
        ElMessage.success('知识库更新成功')
    } catch (e) {
        ElMessage.error('更新知识库失败')
    }
}

const deleteKB = async (id) => {
    if (!(await confirmAction('确定要删除该知识库吗？', '警告'))) return
    try {
        await api.delete(`/knowledge-bases/${id}`)
        fetchKBs()
        ElMessage.success('知识库删除成功')
    } catch (e) {
        ElMessage.error('删除失败')
    }
}

const goToDetail = (id) => {
    router.push(`/knowledge-bases/${id}`)
}

onMounted(fetchKBs)
</script>

<style scoped>
.kb-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 20px;
    margin-top: 20px;
}
.kb-card {
    cursor: pointer;
    position: relative;
    height: 150px;
    display: flex;
    flex-direction: column;
}
.kb-card-header {
    position: absolute;
    top: 10px;
    right: 10px;
}
.kb-icon {
    font-size: 24px;
    color: #409EFF;
}
.kb-card-body {
    padding: 10px;
    flex: 1;
}
.kb-card-body h3 {
    font-weight: bold;
    margin: 0 0 10px 0;
}
.kb-desc {
    color: #666;
    font-size: 0.9em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.kb-card-footer {
    position: absolute;
    bottom: 10px;
    left: 10px;
    right: 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.8em;
    color: #999;
}
.header-actions {
    margin-bottom: 20px;
}
</style>
