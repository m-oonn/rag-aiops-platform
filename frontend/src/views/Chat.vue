<template>
  <div class="chat-container">
    <el-aside width="300px" class="chat-sidebar">
      <div class="config-section" v-if="currentAssistant">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3>{{ currentAssistant.name }}</h3>
            <el-button type="primary" size="small" @click="saveAssistantConfig" v-if="hasConfigChanges">保存</el-button>
        </div>
        <p class="assistant-desc">{{ currentAssistant.description }}</p>
        <el-divider />
        
        <el-form label-position="top" size="small">
             <el-tabs v-model="configTab">
                 <el-tab-pane label="基础" name="basic">
                     <el-form-item label="系统提示词">
                         <el-input type="textarea" v-model="currentAssistant.system_prompt" :rows="4" @input="onConfigChange" />
                     </el-form-item>
                     <el-form-item label="温度">
                         <el-slider v-model="currentAssistant.temperature" :min="0" :max="1" :step="0.1" @input="onConfigChange" />
                     </el-form-item>
                 </el-tab-pane>
                 <el-tab-pane label="检索增强" name="rag">
                     <el-form-item label="Top-K">
                         <el-slider v-model="currentAssistant.rag_config.top_k" :min="1" :max="20" @input="onConfigChange" />
                     </el-form-item>
                     <el-form-item label="重排序">
                         <el-switch v-model="currentAssistant.rag_config.enable_rerank" @change="onConfigChange" />
                     </el-form-item>
                 </el-tab-pane>
                 <el-tab-pane label="版本" name="versions">
                     <div class="version-list">
                         <div v-for="ver in assistantVersions" :key="ver.version" class="version-item">
                             <span>{{ ver.version }}</span>
                             <el-button size="small" type="text" @click="restoreVersion(ver)">恢复</el-button>
                         </div>
                     </div>
                 </el-tab-pane>
             </el-tabs>
        </el-form>
        <el-button type="primary" plain size="small" style="width: 100%; margin-top: 10px;" @click="changeAssistant">切换助手</el-button>
      </div>

      <div class="config-section" v-else>
        <el-select v-model="selectedAssistant" placeholder="选择助手" class="config-select" @change="onAssistantChange">
          <el-option
            v-for="item in assistants"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
        <el-button type="text" @click="$router.push('/assistants')">管理助手</el-button>
        
        <el-divider>或</el-divider>
        
        <el-select v-model="selectedKB" placeholder="直接选择知识库（旧版）" class="config-select" :disabled="!!selectedAssistant">
          <el-option
            v-for="item in kbs"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
      </div>

      <div class="session-list">
        <div class="session-header">
            <span>会话历史</span>
            <el-button type="text" size="small" @click="batchDeleteMode = !batchDeleteMode">{{ batchDeleteMode ? '取消' : '管理' }}</el-button>
        </div>
        <div v-if="batchDeleteMode" class="batch-actions">
            <el-button type="danger" size="small" :disabled="!selectedSessions.length" @click="deleteSelectedSessions">删除选中</el-button>
        </div>
        <div 
          v-for="session in sessions" 
          :key="session.session_uid" 
          class="session-item"
          :class="{ active: currentSessionId === session.session_uid }"
          @click="!batchDeleteMode && loadSession(session)"
        >
          <el-checkbox v-if="batchDeleteMode" v-model="selectedSessions" :label="session.session_uid" @click.stop />
          <span class="session-title">{{ session.title || '新会话' }}</span>
          <el-button v-if="!batchDeleteMode" class="delete-btn" type="text" icon="Delete" @click.stop="deleteSession(session.session_uid)"></el-button>
        </div>
        <el-button @click="newChat" style="width: 100%; margin-top: 10px;" v-if="!batchDeleteMode">新建会话</el-button>
      </div>
    </el-aside>
    
    <el-main class="chat-main">
      <div v-if="currentGreeting" class="greeting-message">
          {{ currentGreeting }}
      </div>
      <div class="messages" ref="messagesContainer">
        <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.role]">
          <div class="message-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
          <div v-if="msg.sources && msg.sources.length" class="sources">
            <small>参考来源：</small>
            <ul>
              <li v-for="src in msg.sources" :key="src.id">
                {{ src.text.substring(0, 50) }}...（相关度：{{ src.score.toFixed(2) }}）
              </li>
            </ul>
          </div>
        </div>
      </div>
      
      <div class="input-area">
        <div class="input-toolbar">
          <el-select v-model="selectedModel" size="small" style="width: 220px;" placeholder="选择模型">
            <el-option
              v-for="m in availableModels"
              :key="m.id"
              :label="m.name"
              :value="m.id"
            />
          </el-select>
        </div>
        <el-input 
          v-model="inputQuery" 
          placeholder="请输入问题..." 
          @keyup.enter="sendMessage"
        >
          <template #append>
            <el-button :disabled="!inputQuery.trim()" @click="sendMessage">发送</el-button>
          </template>
        </el-input>
      </div>
    </el-main>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, nextTick, computed, watch } from 'vue'
import api from '../api'
import { getChatStreamUrl, renderMarkdown } from '../utils/chat'
import { streamSSE } from '../utils/sse'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { confirmAction } from '../utils/confirm'
import { useRoute } from 'vue-router'

const route = useRoute()
const kbs = ref([])
const assistants = ref([])
const selectedKB = ref(null)
const selectedAssistant = ref(null)
const sessions = ref([])
const currentSessionId = ref(null)
const messages = ref([])
const inputQuery = ref('')
const messagesContainer = ref(null)
let streamAbortController = null

// 模型选择器
const selectedModel = ref(null)  // 当前选中的模型 ID，null 表示用默认
const availableModels = ref([])  // 从后端 /health/models 获取的可用模型列表

// Delete features
const batchDeleteMode = ref(false)
const selectedSessions = ref([])

const configTab = ref('basic')
const hasConfigChanges = ref(false)
const assistantVersions = ref([])

const onConfigChange = () => {
    hasConfigChanges.value = true
}

const saveAssistantConfig = async () => {
    try {
        // Increment version logic
        // Simple string increment: v1.0.0 -> v1.0.1
        // We need to fetch current version or assume
        let nextVer = 'v1.0.0'
        if (assistantVersions.value.length > 0) {
            const lastVer = assistantVersions.value[0].version
            const parts = lastVer.replace('v', '').split('.').map(Number)
            parts[2]++
            if (parts[2] >= 10) {
                parts[2] = 0
                parts[1]++
            }
            if (parts[1] >= 10) {
                parts[1] = 0
                parts[0]++
            }
            nextVer = `v${parts.join('.')}`
        }
        
        // Save current state as new version
        const payload = {
            ...currentAssistant.value,
            version: nextVer
        }
        
        await api.put(`/assistants/${currentAssistant.value.id}`, payload)
        await api.post(`/assistants/${currentAssistant.value.id}/versions`, {
            version: nextVer,
            config: payload
        })
        
        ElMessage.success(`已保存为 ${nextVer}`)
        hasConfigChanges.value = false
        fetchVersions()
    } catch (e) {
        ElMessage.error('保存失败')
    }
}

const fetchVersions = async () => {
    if (!currentAssistant.value) return
    try {
        const res = await api.get(`/assistants/${currentAssistant.value.id}/versions`)
        assistantVersions.value = res.data
    } catch (e) {
        // Ignore if endpoint not exists yet
    }
}

const restoreVersion = async (ver) => {
    if (!(await confirmAction(`确认恢复到 ${ver.version}？`))) return
    try {
        // Apply config
        const config = ver.config
        // Update currentAssistant locally
        currentAssistant.value.system_prompt = config.system_prompt
        currentAssistant.value.temperature = config.temperature
        currentAssistant.value.rag_config = config.rag_config

        // Save to backend
        await api.put(`/assistants/${currentAssistant.value.id}`, config)
        ElMessage.success('已恢复')
        hasConfigChanges.value = false
    } catch (e) {
        ElMessage.error('恢复失败')
    }
}

const changeAssistant = () => {
    selectedAssistant.value = null
    currentSessionId.value = null
    messages.value = []
    hasConfigChanges.value = false
}

const currentAssistant = computed(() => {
    if (selectedAssistant.value) {
        return assistants.value.find(a => a.id === selectedAssistant.value)
    }
    return null
})

const currentGreeting = computed(() => {
    if (selectedAssistant.value) {
        const assistant = assistants.value.find(a => a.id === selectedAssistant.value)
        return assistant ? assistant.greeting_message : null
    }
    return null
})

const fetchKBs = async () => {
  const res = await api.get('/knowledge-bases/')
  kbs.value = res.data
}

const fetchAssistants = async () => {
  const res = await api.get('/assistants/')
  assistants.value = res.data
}

const fetchSessions = async () => {
  const res = await api.get('/chat/sessions')
  sessions.value = res.data
}

const onAssistantChange = () => {
  selectedKB.value = null
  // Show greeting if new chat
  if (!currentSessionId.value && currentGreeting.value) {
      // Logic handled in template, but maybe we want to push it as a message?
      // For now, simple banner is fine.
  }
}

const deleteSession = async (uid) => {
    if (!(await confirmAction('确定删除该会话？', '警告'))) return
    try {
        await api.delete(`/chat/sessions/${uid}`)
        fetchSessions()
        if (currentSessionId.value === uid) {
            newChat()
        }
        ElMessage.success('已删除')
    } catch (e) {
        ElMessage.error('删除失败')
    }
}

const deleteSelectedSessions = async () => {
    if (!(await confirmAction(`确定删除 ${selectedSessions.value.length} 个会话？`, '警告'))) return
    try {
        await api.delete('/chat/sessions', { data: selectedSessions.value })
        fetchSessions()
        selectedSessions.value = []
        batchDeleteMode.value = false
        newChat()
        ElMessage.success('批量删除成功')
    } catch (e) {
        ElMessage.error('删除失败')
    }
}

const loadSession = async (session) => {
  currentSessionId.value = session.session_uid
  selectedAssistant.value = session.assistant_id
  const res = await api.get(`/chat/sessions/${session.session_uid}/messages`)
  messages.value = []
  res.data.forEach(m => {
    messages.value.push({ role: 'user', content: m.query })
    messages.value.push({ role: 'assistant', content: m.answer })
  })
  scrollToBottom()
}

const newChat = () => {
  currentSessionId.value = null
  messages.value = []
}

const sendMessage = async () => {
  if (!inputQuery.value.trim()) return

  const query = inputQuery.value
  messages.value.push({ role: 'user', content: query })
  inputQuery.value = ''
  scrollToBottom()

  // 纯聊天(无助手、无知识库)走流式;带助手/KB 的 RAG 路径仍走同步 /chat/
  if (!selectedAssistant.value && !selectedKB.value) {
    await sendMessageStream(query)
    return
  }

  try {
    const payload = {
      query: query,
      session_id: currentSessionId.value,
      llm_model: selectedModel.value,
    }

    if (selectedAssistant.value) {
      payload.assistant_id = selectedAssistant.value
    } else if (selectedKB.value) {
      payload.kb_id = selectedKB.value
    }

    const res = await api.post('/chat/', payload)

    currentSessionId.value = res.data.session_id
    messages.value.push({
      role: 'assistant',
      content: res.data.answer,
      sources: res.data.source_documents
    })
    scrollToBottom()
    if (!sessions.value.find(s => s.session_uid === res.data.session_id)) {
      fetchSessions()
    }
  } catch (e) {
    console.error(e)
    messages.value.push({ role: 'system', content: '发送消息失败：' + (e.response?.data?.detail || e.message) })
  }
}

// 纯聊天流式: fetch + ReadableStream 解析 SSE(端点是 POST,原生 EventSource 只支持 GET)
const sendMessageStream = async (query) => {
  // 若上一条流式请求仍在进行，先中止，避免并发
  if (streamAbortController) {
    streamAbortController.abort()
  }
  streamAbortController = new AbortController()

  // 先放一条空的 assistant 占位消息,后续逐 token 追加
  const assistantMsg = reactive({ role: 'assistant', content: '' })
  messages.value.push(assistantMsg)
  scrollToBottom()

  const handleEvent = (evt) => {
    if (evt.type === 'token') {
      assistantMsg.content += evt.content
      scrollToBottom()
    } else if (evt.type === 'done') {
      currentSessionId.value = evt.session_id
      if (!sessions.value.find(s => s.session_uid === evt.session_id)) {
        fetchSessions()
      }
    } else if (evt.type === 'error') {
      ElMessage.error(evt.message || '聊天出错')
    }
  }

  try {
    await streamSSE(
      getChatStreamUrl(),
      { query, session_id: currentSessionId.value, llm_model: selectedModel.value },
      {
        signal: streamAbortController.signal,
        onEvent: handleEvent,
        showMessage: (msg) => ElMessage.error(msg),
      }
    )
  } catch (e) {
    if (e.name === 'AbortError') {
      // 用户主动中断，不显示错误
      return
    }
    console.error(e)
    if (!assistantMsg.content) {
      assistantMsg.role = 'system'
      assistantMsg.content = '发送消息失败：' + (e.message || '')
    }
    ElMessage.error(e.message || '聊天请求异常')
  } finally {
    streamAbortController = null
  }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

const fetchModels = async () => {
  try {
    const res = await api.get('/health/models')
    availableModels.value = res.data.models || []
    selectedModel.value = res.data.default_model || null
  } catch (e) {
    // 降级：API 不可用时提供默认选项
    availableModels.value = [
      { id: 'qwen-max', name: 'Qwen-Max (旗舰)' },
      { id: 'qwen-plus', name: 'Qwen-Plus (均衡)' },
      { id: 'qwen-turbo', name: 'Qwen-Turbo (快速)' },
    ]
    selectedModel.value = 'qwen-max'
  }
}

onMounted(async () => {
  await Promise.all([
    fetchKBs(),
    fetchAssistants(),
    fetchSessions(),
    fetchModels()
  ])

  if (route.query.assistant_id) {
      selectedAssistant.value = parseInt(route.query.assistant_id)
      fetchVersions()
  }
})

onUnmounted(() => {
  if (streamAbortController) {
    streamAbortController.abort()
    streamAbortController = null
  }
})

watch(selectedAssistant, (newVal) => {
    if (newVal) fetchVersions()
    // 切换助手后，当前会话上下文不再适用，清空历史
    newChat()
})

watch(selectedKB, () => {
    // 切换直接 KB 后，清空历史避免上下文错乱
    newChat()
})
</script>

<style scoped>
.chat-container {
  display: flex;
  height: calc(100vh - 100px);
}
.chat-sidebar {
  border-right: 1px solid #eee;
  padding: 10px;
  display: flex;
  flex-direction: column;
}
.config-section {
  margin-bottom: 20px;
}
.session-list {
    flex: 1;
    overflow-y: auto;
}
.session-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
    font-weight: bold;
}
.session-item {
  padding: 10px;
  cursor: pointer;
  border-radius: 4px;
  margin-bottom: 5px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.session-item:hover, .session-item.active {
  background-color: #f5f7fa;
}
.session-title {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
}
.delete-btn {
    display: none;
    color: #F56C6C;
}
.session-item:hover .delete-btn {
    display: block;
}
.chat-main {
  display: flex;
  flex-direction: column;
  padding: 0;
}
.greeting-message {
    padding: 15px;
    background-color: #f0f9eb;
    color: #67c23a;
    border-bottom: 1px solid #e1f3d8;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}
.message {
  margin-bottom: 15px;
  max-width: 80%;
}
.message.user {
  margin-left: auto;
  background-color: #e3f2fd;
  padding: 10px;
  border-radius: 10px;
}
.message.assistant {
  margin-right: auto;
  background-color: #f5f5f5;
  padding: 10px;
  border-radius: 10px;
}
.input-area {
  padding: 20px;
  border-top: 1px solid #eee;
}
.input-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  gap: 10px;
}
.sources {
  margin-top: 5px;
  font-size: 0.8em;
  color: #666;
}
.config-select {
  width: 100%;
  margin-bottom: 10px;
}
.session-item {
  padding: 10px;
  cursor: pointer;
  border-bottom: 1px solid #eee;
}
.session-item:hover {
  background-color: #f0f0f0;
}
/* Markdown 渲染样式 */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin-top: 0.6em;
  margin-bottom: 0.3em;
  font-weight: 600;
}
.markdown-body :deep(p) {
  margin: 0.4em 0;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 1.5em;
  margin: 0.4em 0;
}
.markdown-body :deep(code) {
  background-color: #f0f0f0;
  padding: 0.15em 0.4em;
  border-radius: 3px;
  font-size: 0.9em;
}
.markdown-body :deep(pre) {
  background-color: #f5f5f5;
  padding: 0.8em;
  border-radius: 6px;
  overflow-x: auto;
  margin: 0.5em 0;
}
.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
}
.markdown-body :deep(strong) {
  font-weight: 700;
}
.markdown-body :deep(blockquote) {
  border-left: 3px solid #ddd;
  padding-left: 0.8em;
  color: #666;
  margin: 0.5em 0;
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 0.5em 0;
  width: 100%;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #ddd;
  padding: 0.4em 0.6em;
  text-align: left;
}
.markdown-body :deep(th) {
  background-color: #f5f5f5;
  font-weight: 600;
}
</style>
