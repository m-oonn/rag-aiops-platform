<template>
  <div class="chat-container">
    <el-aside width="300px" class="chat-sidebar">
      <div class="config-section" v-if="currentAssistant">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3>{{ currentAssistant.name }}</h3>
            <el-button type="primary" size="small" @click="saveAssistantConfig" v-if="hasConfigChanges">Save</el-button>
        </div>
        <p class="assistant-desc">{{ currentAssistant.description }}</p>
        <el-divider />
        
        <el-form label-position="top" size="small">
             <el-tabs v-model="configTab">
                 <el-tab-pane label="Basic" name="basic">
                     <el-form-item label="System Prompt">
                         <el-input type="textarea" v-model="currentAssistant.system_prompt" :rows="4" @input="onConfigChange" />
                     </el-form-item>
                     <el-form-item label="Temperature">
                         <el-slider v-model="currentAssistant.temperature" :min="0" :max="1" :step="0.1" @input="onConfigChange" />
                     </el-form-item>
                 </el-tab-pane>
                 <el-tab-pane label="RAG" name="rag">
                     <el-form-item label="Top-K">
                         <el-slider v-model="currentAssistant.rag_config.top_k" :min="1" :max="20" @input="onConfigChange" />
                     </el-form-item>
                     <el-form-item label="Rerank">
                         <el-switch v-model="currentAssistant.rag_config.enable_rerank" @change="onConfigChange" />
                     </el-form-item>
                 </el-tab-pane>
                 <el-tab-pane label="Versions" name="versions">
                     <div class="version-list">
                         <div v-for="ver in assistantVersions" :key="ver.version" class="version-item">
                             <span>{{ ver.version }}</span>
                             <el-button size="small" type="text" @click="restoreVersion(ver)">Restore</el-button>
                         </div>
                     </div>
                 </el-tab-pane>
             </el-tabs>
        </el-form>
        <el-button type="primary" plain size="small" style="width: 100%; margin-top: 10px;" @click="changeAssistant">Switch Assistant</el-button>
      </div>

      <div class="config-section" v-else>
        <el-select v-model="selectedAssistant" placeholder="Select Assistant" class="config-select" @change="onAssistantChange">
          <el-option
            v-for="item in assistants"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
        <el-button type="text" @click="$router.push('/assistants')">Manage Assistants</el-button>
        
        <el-divider>OR</el-divider>
        
        <el-select v-model="selectedKB" placeholder="Direct KB (Legacy)" class="config-select" :disabled="!!selectedAssistant">
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
            <span>History</span>
            <el-button type="text" size="small" @click="batchDeleteMode = !batchDeleteMode">{{ batchDeleteMode ? 'Cancel' : 'Manage' }}</el-button>
        </div>
        <div v-if="batchDeleteMode" class="batch-actions">
            <el-button type="danger" size="small" :disabled="!selectedSessions.length" @click="deleteSelectedSessions">Delete Selected</el-button>
        </div>
        <div 
          v-for="session in sessions" 
          :key="session.session_uid" 
          class="session-item"
          :class="{ active: currentSessionId === session.session_uid }"
          @click="!batchDeleteMode && loadSession(session)"
        >
          <el-checkbox v-if="batchDeleteMode" v-model="selectedSessions" :label="session.session_uid" @click.stop />
          <span class="session-title">{{ session.title || 'New Chat' }}</span>
          <el-button v-if="!batchDeleteMode" class="delete-btn" type="text" icon="Delete" @click.stop="deleteSession(session.session_uid)"></el-button>
        </div>
        <el-button @click="newChat" style="width: 100%; margin-top: 10px;" v-if="!batchDeleteMode">New Chat</el-button>
      </div>
    </el-aside>
    
    <el-main class="chat-main">
      <div v-if="currentGreeting" class="greeting-message">
          {{ currentGreeting }}
      </div>
      <div class="messages" ref="messagesContainer">
        <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.role]">
          <div class="message-content" style="white-space: pre-wrap;">{{ msg.content }}</div>
          <div v-if="msg.sources && msg.sources.length" class="sources">
            <small>Sources:</small>
            <ul>
              <li v-for="src in msg.sources" :key="src.id">
                {{ src.text.substring(0, 50) }}... (Score: {{ src.score.toFixed(2) }})
              </li>
            </ul>
          </div>
        </div>
      </div>
      
      <div class="input-area">
        <el-input 
          v-model="inputQuery" 
          placeholder="Type your question..." 
          @keyup.enter="sendMessage"
        >
          <template #append>
            <el-button @click="sendMessage">Send</el-button>
          </template>
        </el-input>
      </div>
    </el-main>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, computed, watch } from 'vue'
import api from '../api'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
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
        
        ElMessage.success(`Saved as ${nextVer}`)
        hasConfigChanges.value = false
        fetchVersions()
    } catch (e) {
        ElMessage.error('Save failed')
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
    try {
        await ElMessageBox.confirm(`Restore to ${ver.version}?`, 'Confirm')
        // Apply config
        const config = ver.config
        // Update currentAssistant locally
        currentAssistant.value.system_prompt = config.system_prompt
        currentAssistant.value.temperature = config.temperature
        currentAssistant.value.rag_config = config.rag_config
        
        // Save to backend
        await api.put(`/assistants/${currentAssistant.value.id}`, config)
        ElMessage.success('Restored')
        hasConfigChanges.value = false
    } catch (e) {
        if (e !== 'cancel') ElMessage.error('Restore failed')
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
    try {
        await ElMessageBox.confirm('Delete this session?', 'Warning', { type: 'warning' })
        await api.delete(`/chat/sessions/${uid}`)
        fetchSessions()
        if (currentSessionId.value === uid) {
            newChat()
        }
        ElMessage.success('Deleted')
    } catch (e) {
        if (e !== 'cancel') ElMessage.error('Failed')
    }
}

const deleteSelectedSessions = async () => {
    try {
        await ElMessageBox.confirm(`Delete ${selectedSessions.value.length} sessions?`, 'Warning', { type: 'warning' })
        await api.delete('/chat/sessions', { data: selectedSessions.value })
        fetchSessions()
        selectedSessions.value = []
        batchDeleteMode.value = false
        newChat()
        ElMessage.success('Batch deleted')
    } catch (e) {
        if (e !== 'cancel') ElMessage.error('Failed')
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
  
  try {
    const payload = {
      query: query,
      session_id: currentSessionId.value,
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
    messages.value.push({ role: 'system', content: 'Error sending message: ' + (e.response?.data?.detail || e.message) })
  }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

onMounted(async () => {
  await fetchKBs()
  await fetchAssistants()
  await fetchSessions()
  
  if (route.query.assistant_id) {
      selectedAssistant.value = parseInt(route.query.assistant_id)
      fetchVersions()
  }
})

watch(selectedAssistant, (newVal) => {
    if (newVal) fetchVersions()
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
</style>
