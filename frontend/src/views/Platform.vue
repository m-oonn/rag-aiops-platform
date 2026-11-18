<script setup>
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { request } from "../lib/api";
import { useLoad, dateTime, tone } from "../lib/ui";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import Icon from "../components/Icon.vue";
const route = useRoute(),
  router = useRouter(),
  tab = ref(
    ["queues", "models"].includes(route.query.tab)
      ? route.query.tab
      : "services",
  ),
  health = ref(null),
  dependencies = ref(null),
  queues = ref(null),
  models = ref(null),
  refreshAt = ref(null),
  sourceErrors = ref([]);
const names = {
  llm: "语言模型",
  milvus: "向量检索",
  minio: "文件存储",
  redis: "缓存",
  rabbitmq: "消息队列",
  probe: "主机采集",
  mcp_monitor: "指标服务",
  mcp_cls: "日志服务",
};
const rows = computed(() =>
  Object.entries(dependencies.value?.services || {}).map(([key, value]) => ({
    name: names[key] || key,
    ...value,
  })),
);
const { loading, error, refresh } = useLoad(
  async () => {
    const results = await Promise.allSettled([
      request("/health"),
      request("/health/dependencies"),
      request("/health/queues"),
      request("/health/models"),
    ]);
    const targets = [health, dependencies, queues, models];
    sourceErrors.value = results.map((result, index) => {
      targets[index].value =
        result.status === "fulfilled" ? result.value : null;
      return result.status === "rejected" ? result.reason.message : "";
    });
    if (results.every((r) => r.status === "rejected")) throw results[0].reason;
    refreshAt.value = new Date();
  },
  { interval: 30000 },
);
function setTab(value) {
  tab.value = value;
  router.replace({ query: value === "services" ? {} : { tab: value } });
}
</script>
<template>
  <div class="page">
    <PageHeader title="运行状态"
      ><span v-if="refreshAt" class="muted"
        >更新于 {{ dateTime(refreshAt) }}</span
      ><button class="button" :disabled="loading" @click="refresh()">
        <Icon name="refresh" :size="16" />刷新
      </button></PageHeader
    ><Feedback
      v-if="error && !health && !dependencies && !queues"
      :error="error"
      @retry="refresh()"
    /><template v-else
      ><div class="summary-line">
        <span
          >API
          <span :class="['status', tone(health?.status)]">{{
            health?.status === "ok" ? "正常" : health?.status || "未知"
          }}</span></span
        ><span>版本 {{ health?.version || "—" }}</span
        ><span
          >依赖
          {{
            dependencies?.overall === "ok"
              ? "正常"
              : dependencies?.overall === "degraded"
                ? "部分不可用"
                : "—"
          }}</span
        ><span v-if="error" class="text-danger">{{ error }}</span>
      </div>
      <nav class="tabs">
        <button
          :class="{ active: tab === 'services' }"
          @click="setTab('services')"
        >
          服务状态</button
        ><button
          :class="{ active: tab === 'queues' }"
          @click="setTab('queues')"
        >
          任务队列</button
        ><button
          :class="{ active: tab === 'models' }"
          @click="setTab('models')"
        >
          模型
        </button>
      </nav>
      <section v-if="tab === 'services'">
        <Feedback
          v-if="sourceErrors[1]"
          :error="sourceErrors[1]"
          @retry="refresh()"
        />
        <Feedback
          v-else-if="!rows.length"
          :loading="loading"
          :empty="!loading"
          text="暂无服务数据"
        />
        <div v-for="row in rows" :key="row.name" class="service-line">
          <span>{{ row.name }}</span>
          <div class="actions">
            <span :class="['status', tone(row.status)]">{{
              row.status === "ok"
                ? "正常"
                : row.status === "disabled"
                  ? "未启用"
                  : "不可用"
            }}</span
            ><span v-if="row.error" class="muted">{{ row.error }}</span>
          </div>
        </div>
      </section>
      <section v-if="tab === 'queues'">
        <Feedback
          v-if="!queues"
          :loading="loading"
          :error="sourceErrors[2]"
          @retry="refresh()"
        />
        <div
          v-else-if="queues.status !== 'ok'"
          class="inline-feedback"
          role="status"
        >
          {{ queues.message || `队列状态：${queues.status}` }}
        </div>
        <template v-else
          ><div class="metric-strip queue-metrics">
            <div>
              <span>执行中</span
              ><strong>{{ queues.summary?.active_tasks ?? 0 }}</strong>
            </div>
            <div>
              <span>等待中</span
              ><strong>{{ queues.summary?.reserved_tasks ?? 0 }}</strong>
            </div>
            <div>
              <span>定时任务</span
              ><strong>{{ queues.summary?.scheduled_tasks ?? 0 }}</strong>
            </div>
            <div>
              <span>在线处理节点</span
              ><strong>{{ queues.summary?.workers ?? 0 }}</strong>
            </div>
          </div>
          <h2>执行任务</h2>
          <div
            v-for="(tasks, worker) in queues.details?.active || {}"
            :key="worker"
          >
            <h3 class="section">{{ worker }}</h3>
            <div v-for="task in tasks" :key="task.id" class="record-row">
              <Icon name="tasks" />
              <div class="grow">
                <strong>{{ task.name }}</strong
                ><span class="muted truncate">{{ task.id }}</span>
              </div>
              <time class="muted">{{
                task.time_start ? dateTime(task.time_start * 1000) : "—"
              }}</time>
            </div>
          </div>
          <div
            v-if="!Object.values(queues.details?.active || {}).flat().length"
            class="empty-state compact"
          >
            当前没有执行中的任务
          </div>
          <h2 class="section">处理节点</h2>
          <div
            v-for="(worker, name) in queues.details?.worker_stats || {}"
            :key="name"
            class="service-line"
          >
            <span>{{ name }}</span
            ><span class="muted"
              >{{ worker.pool?.["max-concurrency"] || "—" }} 并发 ·
              {{ worker.pool?.processes?.length || 0 }} 个进程</span
            >
          </div></template
        >
      </section>
      <section v-if="tab === 'models'">
        <Feedback
          v-if="sourceErrors[3]"
          :error="sourceErrors[3]"
          @retry="refresh()"
        />
        <Feedback
          v-else-if="!models?.models?.length"
          :loading="loading"
          :empty="!loading"
          text="暂无模型配置"
        />
        <div
          v-for="model in models?.models || []"
          :key="model.id"
          class="record-row"
        >
          <Icon name="spark" />
          <div class="grow">
            <strong>{{ model.name }}</strong
            ><span class="muted">{{ model.id }}</span>
          </div>
          <span v-if="model.id === models.default_model" class="tag"
            >默认模型</span
          >
        </div>
      </section></template
    >
  </div>
</template>
