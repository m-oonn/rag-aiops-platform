<script setup>
import { computed, reactive, ref } from "vue";
import { request } from "../lib/api";
import { applicationBody, assistantConfig } from "../lib/applications";
import { confirmAction, fail, notify, useLoad, dateTime } from "../lib/ui";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import DataTable from "../components/DataTable.vue";
import Modal from "../components/Modal.vue";
import Markdown from "../components/Markdown.vue";
import Icon from "../components/Icon.vue";
const props = defineProps({ kind: String });
const isAgent = computed(() => props.kind === "agents"),
  endpoint = computed(() => (isAgent.value ? "/agents/" : "/assistants/")),
  title = computed(() => (isAgent.value ? "智能体" : "助手"));
const agents = ref([]),
  versions = ref([]),
  versionTarget = ref(null),
  versionOpen = ref(false),
  versionError = ref("");
const rows = ref([]),
  kbs = ref([]),
  models = ref([]),
  search = ref(""),
  modal = ref(false),
  editing = ref(null),
  busy = ref(false),
  executeTarget = ref(null),
  result = ref(null);
const query = ref(""),
  qaQuery = ref(""),
  answer = ref(""),
  editTabs = ["基本信息", "知识与工具", "模型与记忆"];
const activeTab = ref(editTabs[0]),
  execution = ref(false);
const form = reactive({
  name: "",
  description: "",
  greeting_message: "",
  agent_ids: [],
  type: "function_call",
  system_prompt: "",
  assistant_id: "",
  llm_model: "",
  temperature: 0.7,
  max_tokens: 2048,
  top_p: 1,
  knowledge_config: { kb_ids: [], top_k: 5, recall_strategy: "hybrid" },
  memory_config: {
    enable_short_term: true,
    window_size: 10,
    enable_long_term: false,
  },
  reasoning_config: { max_steps: 10, allow_parallel: true },
  security_config: {
    safety_level: "moderate",
    allowed_actions: [],
    allow_internet: false,
  },
  interaction_config: {
    output_format: "markdown",
    response_style: "professional",
    clarify_enabled: true,
  },
  execution_config: {
    max_iterations: 5,
    llm_timeout: 60,
    tool_timeout: 30,
    mcp_load_timeout: 15,
  },
  toolRows: [],
});
const filtered = computed(() =>
  rows.value.filter((row) =>
    `${row.name} ${row.description || ""}`
      .toLowerCase()
      .includes(search.value.toLowerCase()),
  ),
);
const { loading, error, refresh } = useLoad(async () => {
  const results = await Promise.allSettled([
    request(endpoint.value),
    request("/knowledge-bases/"),
    request("/health/models"),
    request("/agents/"),
  ]);
  if (results[0].status === "rejected") throw results[0].reason;
  rows.value = results[0].value;
  agents.value = results[3].status === "fulfilled" ? results[3].value : [];
  kbs.value = results[1].status === "fulfilled" ? results[1].value : [];
  if (results[2].status === "fulfilled")
    models.value = results[2].value.models || [];
});
function open(row = null) {
  editing.value = row;
  activeTab.value = editTabs[0];
  const cfg = row || {};
  const model = cfg.llm_config || {};
  Object.assign(form, {
    name: row?.name || "",
    description: row?.description || "",
    greeting_message: cfg.greeting_message || "",
    agent_ids: [...(cfg.agent_ids || [])],
    type: row?.type || "function_call",
    system_prompt: row?.system_prompt || "",
    llm_model: model.model || cfg.llm_model || "",
    temperature: model.temperature ?? cfg.temperature ?? 0.7,
    max_tokens: model.max_tokens ?? 2048,
    top_p: model.top_p ?? 1,
    knowledge_config: {
      kb_ids: cfg.knowledge_config?.kb_ids || cfg.kb_ids || [],
      top_k: cfg.knowledge_config?.top_k || cfg.rag_config?.top_k || 5,
      recall_strategy: cfg.knowledge_config?.recall_strategy || "hybrid",
    },
    memory_config: {
      ...cfg.memory_config,
      enable_short_term:
        cfg.memory_config?.enable_short_term ??
        cfg.memory_config?.enable ??
        true,
      window_size: cfg.memory_config?.window_size || 10,
      enable_long_term: cfg.memory_config?.enable_long_term ?? false,
    },
    reasoning_config: {
      max_steps:
        cfg.reasoning_config?.max_steps ||
        cfg.execution_config?.max_iterations ||
        5,
      allow_parallel: cfg.reasoning_config?.allow_parallel ?? false,
    },
    security_config: cfg.security_config || {
      safety_level: "moderate",
      allowed_actions: [],
      allow_internet: false,
    },
    interaction_config: cfg.interaction_config || {
      output_format: "markdown",
      response_style: "professional",
      clarify_enabled: true,
    },
    execution_config: {
      max_iterations: cfg.execution_config?.max_iterations || 5,
      llm_timeout: cfg.execution_config?.llm_timeout || 60,
      tool_timeout: cfg.execution_config?.tool_timeout || 30,
      mcp_load_timeout: cfg.execution_config?.mcp_load_timeout || 15,
    },
    toolRows: Object.entries(cfg.tools_config || {}).map(([name, value]) => ({
      name,
      url: value.url || "",
      transport: value.transport || "streamable_http",
    })),
  });
  modal.value = true;
}
function addTool() {
  form.toolRows.push({ name: "", url: "", transport: "streamable_http" });
}
async function save(event) {
  if (!form.name.trim()) {
    activeTab.value = editTabs[0];
    return fail(new Error("请填写名称"));
  }
  const element = document.querySelector("#application-form");
  if (element && !element.reportValidity()) return;
  const names = new Set();
  for (const tool of form.toolRows) {
    if (!tool.name.trim() || !/^https?:\/\//i.test(tool.url.trim())) {
      activeTab.value = editTabs[1];
      return fail(new Error("请补全工具名称与 HTTP 地址"));
    }
    if (names.has(tool.name.trim())) return fail(new Error("工具服务名称重复"));
    names.add(tool.name.trim());
  }
  busy.value = true;
  try {
    const body = applicationBody(form, editing.value || {}, isAgent.value);
    await request(
      editing.value ? endpoint.value + editing.value.id : endpoint.value,
      { method: editing.value ? "PUT" : "POST", body },
    );
    modal.value = false;
    await refresh();
    notify(title.value + "已保存");
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
async function remove(row) {
  if (
    !(await confirmAction(
      `删除${title.value}`,
      `删除“${row.name}”？此操作无法撤销。`,
      "删除",
      true,
    ))
  )
    return;
  try {
    await request(`${endpoint.value}${row.id}`, { method: "DELETE" });
    await refresh();
    notify(`${title.value}已删除`);
  } catch (e) {
    fail(e);
  }
}
async function execute() {
  if (!query.value.trim()) return;
  execution.value = true;
  result.value = null;
  try {
    result.value = await request(`/agents/${executeTarget.value.id}/execute`, {
      method: "POST",
      body: { query: query.value.trim() },
    });
  } catch (e) {
    fail(e);
  } finally {
    execution.value = false;
  }
}
async function sendQuestion() {
  if (!qaQuery.value.trim()) return;
  busy.value = true;
  answer.value = "";
  try {
    const data = await request("/chat/", {
      method: "POST",
      body: {
        query: qaQuery.value.trim(),
        assistant_id: executeTarget.value?.id,
        top_k: 5,
      },
    });
    answer.value = data.answer;
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
async function createVersion(row) {
  try {
    const versions = await request(`/assistants/${row.id}/versions`);
    const next = `v-${Date.now()}`;
    await request(`/assistants/${row.id}/versions`, {
      method: "POST",
      body: { version: next, config: assistantConfig(row) },
    });
    notify(`已保存 ${next}`);
  } catch (e) {
    fail(e);
  }
}
async function showVersions(row) {
  versionTarget.value = row;
  versions.value = [];
  versionError.value = "";
  versionOpen.value = true;
  try {
    versions.value = await request(`/assistants/${row.id}/versions`);
  } catch (e) {
    versionError.value = e.message;
  }
}
async function restoreVersion(version) {
  if (
    !(await confirmAction(
      "恢复助手版本",
      "将当前配置替换为 " + version.version + "？",
      "恢复",
    ))
  )
    return;
  try {
    await request(`/assistants/${versionTarget.value.id}`, {
      method: "PUT",
      body: assistantConfig(version.config),
    });
    versionOpen.value = false;
    await refresh();
    notify("版本已恢复");
  } catch (e) {
    fail(e);
  }
}
</script>
<template>
  <div class="page">
    <PageHeader :title="title"
      ><button class="button" :disabled="loading" @click="refresh()">
        <Icon name="refresh" :size="16" />刷新</button
      ><button class="button primary" @click="open()">
        <Icon name="plus" :size="17" />新建{{
          title === "助手" ? "助手" : "智能体"
        }}
      </button></PageHeader
    >
    <div class="toolbar">
      <label class="search-input"
        ><Icon name="search" /><input
          v-model="search"
          type="search"
          :placeholder="`搜索${title}`"
          :aria-label="`搜索${title}`" /></label
      ><span class="muted">{{ filtered.length }} 项</span>
    </div>
    <Feedback
      :loading="loading"
      :error="error"
      :empty="!filtered.length && !loading"
      :text="`暂无${title}`"
      @retry="refresh()"
    /><DataTable
      v-if="filtered.length"
      :rows="filtered"
      :columns="[
        { key: 'name', label: title, width: '32%' },
        { key: 'type', label: '类型' },
        { key: 'model', label: '模型' },
        { key: 'created_at', label: '创建时间' },
        { key: 'actions', label: '' },
      ]"
      ><template #name="{ row }"
        ><div class="cell-title">
          <Icon :name="isAgent ? 'workflow' : 'spark'" />
          <div>
            <strong>{{ row.name }}</strong
            ><span v-if="row.description" class="cell-subtitle">{{
              row.description
            }}</span>
          </div>
        </div></template
      ><template #type="{ row }"
        ><span class="tag">{{ row.type || "对话助手" }}</span></template
      ><template #model="{ row }">{{
        row.llm_config?.model || row.llm_model || "默认模型"
      }}</template
      ><template #created_at="{ row }">{{ dateTime(row.created_at) }}</template
      ><template #actions="{ row }"
        ><div class="actions">
          <button class="text-button" @click="open(row)">编辑</button
          ><button
            v-if="isAgent"
            class="text-button"
            @click="
              executeTarget = row;
              query = '';
              result = null;
            "
          >
            试运行</button
          ><button
            v-else
            class="text-button"
            @click="
              executeTarget = row;
              qaQuery = '';
              answer = '';
            "
          >
            对话</button
          ><button
            v-if="!isAgent"
            class="text-button"
            @click="createVersion(row)"
          >
            保存版本</button
          ><button
            v-if="!isAgent"
            class="text-button"
            @click="showVersions(row)"
          >
            历史版本</button
          ><button class="text-button danger" @click="remove(row)">删除</button>
        </div></template
      ></DataTable
    ><Modal
      v-model="modal"
      :title="`${editing ? '编辑' : '新建'}${title === '助手' ? '助手' : '智能体'}`"
      wide
      ><nav class="tabs">
        <button
          v-for="tab in editTabs"
          :key="tab"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >
          {{ tab }}
        </button>
      </nav>
      <form
        id="application-form"
        @submit.prevent="save"
        class="application-form"
      >
        <template v-if="activeTab === editTabs[0]"
          ><div class="field-grid">
            <label class="field"
              >名称<input
                v-model.trim="form.name"
                required
                maxlength="120" /></label
            ><label v-if="isAgent" class="field"
              >类型<select v-model="form.type">
                <option value="function_call">工具调用</option>
                <option value="react">推理与执行</option>
                <option value="chat">对话</option>
              </select></label
            ><label class="field full"
              >{{ isAgent ? "系统提示词" : "助手指令"
              }}<textarea
                v-model="form.system_prompt"
                rows="10"
                maxlength="12000"
              /></label
            ><label class="field full"
              >描述<textarea
                v-model="form.description"
                rows="2"
                maxlength="1000"
              /></label
            ><label v-if="!isAgent" class="field full"
              >欢迎语<textarea
                v-model="form.greeting_message"
                rows="2"
                maxlength="1000"
              />
            </label></div></template
        ><template v-else-if="activeTab === editTabs[1]"
          ><template v-if="isAgent"
            ><div class="section-heading">
              <h3>MCP 工具服务</h3>
              <button type="button" class="text-button" @click="addTool">
                <Icon name="plus" :size="16" />添加服务
              </button>
            </div>
            <div v-for="(tool, i) in form.toolRows" :key="i" class="tool-row">
              <label class="field"
                >服务名称<input v-model.trim="tool.name" /></label
              ><label class="field"
                >服务地址<input v-model.trim="tool.url" type="url" /></label
              ><label class="field"
                >连接方式<select v-model="tool.transport">
                  <option value="streamable_http">HTTP</option>
                  <option value="sse">SSE</option>
                </select></label
              ><button
                type="button"
                class="icon-button"
                :aria-label="`删除工具服务 ${tool.name || i + 1}`"
                @click="form.toolRows.splice(i, 1)"
              >
                <Icon name="close" :size="17" />
              </button>
            </div>
            <Feedback
              v-if="!form.toolRows.length"
              :empty="true"
              text="尚未添加工具服务"
          /></template>
          <div class="form-section">
            <h3>知识库</h3>
            <div class="check-list">
              <label v-for="kb in kbs" :key="kb.id" class="check-label"
                ><input
                  v-model="form.knowledge_config.kb_ids"
                  type="checkbox"
                  :value="kb.id"
                />{{ kb.name }}</label
              ><span v-if="!kbs.length" class="muted">暂无知识库</span>
            </div>
            <label class="field"
              >检索数量<input
                v-model.number="form.knowledge_config.top_k"
                type="number"
                min="1"
                max="50"
            /></label>
          </div>
          <div v-if="!isAgent" class="form-section">
            <h3>关联智能体</h3>
            <div class="check-list">
              <label v-for="agent in agents" :key="agent.id" class="check-label"
                ><input
                  v-model="form.agent_ids"
                  type="checkbox"
                  :value="agent.id"
                />{{ agent.name }}</label
              ><span v-if="!agents.length" class="muted">暂无智能体</span>
            </div>
          </div> </template
        ><template v-else
          ><div class="field-grid">
            <label class="field"
              >模型<select v-model="form.llm_model">
                <option value="">系统默认</option>
                <option
                  v-for="model in models"
                  :key="model.id"
                  :value="model.id"
                >
                  {{ model.name }}
                </option>
              </select></label
            ><label class="field"
              >随机度<input
                v-model.number="form.temperature"
                type="number"
                min="0"
                max="2"
                step="0.05"
            /></label>
          </div>
          <div v-if="isAgent" class="field-grid">
            <label class="field"
              >最大输出长度<input
                v-model.number="form.max_tokens"
                type="number"
                min="1"
                required /></label
            ><label class="field"
              >采样范围<input
                v-model.number="form.top_p"
                type="number"
                min="0"
                max="1"
                step="0.05"
                required /></label
            ><label class="field"
              >最大执行轮次<input
                v-model.number="form.execution_config.max_iterations"
                type="number"
                min="1"
                max="20"
                required /></label
            ><label class="field"
              >模型等待时间（秒）<input
                v-model.number="form.execution_config.llm_timeout"
                type="number"
                min="1"
                required /></label
            ><label class="field"
              >工具等待时间（秒）<input
                v-model.number="form.execution_config.tool_timeout"
                type="number"
                min="1"
                required /></label
            ><label class="field"
              >工具连接等待时间（秒）<input
                v-model.number="form.execution_config.mcp_load_timeout"
                type="number"
                min="1"
                required
            /></label>
          </div>
          <div class="form-section">
            <h3>对话记忆</h3>
            <label class="check-label"
              ><input
                v-model="form.memory_config.enable_short_term"
                type="checkbox"
              />短期记忆</label
            ><label class="field"
              >记忆窗口<input
                v-model.number="form.memory_config.window_size"
                type="number"
                min="1"
                max="100"
                required /></label
            ><label class="check-label"
              ><input
                v-model="form.memory_config.enable_long_term"
                type="checkbox"
              />长期记忆</label
            >
          </div></template
        >
      </form>
      <template #footer
        ><div class="form-actions">
          <button class="button" @click="modal = false">取消</button
          ><button
            class="button primary"
            type="submit"
            form="application-form"
            :disabled="busy"
          >
            {{ busy ? "保存中…" : "保存" }}
          </button>
        </div></template
      ></Modal
    ><Modal
      :model-value="Boolean(executeTarget)"
      :title="`${executeTarget?.name || ''}${isAgent ? ' · 试运行' : ' · 对话'}`"
      wide
      @update:model-value="!$event && (executeTarget = null)"
      ><template v-if="isAgent"
        ><form @submit.prevent="execute">
          <label class="field"
            >任务<input
              v-model.trim="query"
              placeholder="输入需要处理的任务"
              maxlength="8000"
              required /></label
          ><button
            class="button primary"
            :disabled="execution || !query.trim()"
          >
            <span v-if="execution" class="spinner" />运行
          </button>
        </form>
        <section v-if="result" class="section">
          <h3>执行结果</h3>
          <Markdown :content="result.answer" />
          <div
            v-for="(tool, i) in result.tool_calls || []"
            :key="i"
            class="record-row"
          >
            <span class="tag">{{ tool.name }}</span
            ><code>{{ JSON.stringify(tool.args) }}</code>
          </div>
          <div v-if="result.degradation" class="inline-feedback">
            {{ result.degradation }}
          </div>
        </section></template
      ><template v-else
        ><form @submit.prevent="sendQuestion">
          <label class="field"
            >消息<textarea
              v-model="qaQuery"
              rows="3"
              maxlength="12000"
              required
            /></label
          ><button class="button primary" :disabled="busy">
            <span v-if="busy" class="spinner" />发送
          </button>
        </form>
        <section v-if="answer" class="section">
          <Markdown :content="answer" /></section></template></Modal
    ><Modal
      v-model="versionOpen"
      :title="`历史版本 · ${versionTarget?.name || ''}`"
      ><Feedback
        v-if="versionError"
        :error="versionError"
        @retry="showVersions(versionTarget)"
      /><Feedback v-else :empty="!versions.length" text="暂无历史版本" />
      <div
        v-for="version in versions"
        :key="version.version"
        class="record-row"
      >
        <div class="grow">
          <strong>{{ version.version }}</strong
          ><span class="muted">{{ dateTime(version.created_at) }}</span>
        </div>
        <button class="text-button" @click="restoreVersion(version)">
          恢复
        </button>
      </div></Modal
    >
  </div>
</template>
