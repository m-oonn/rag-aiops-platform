<script setup>
import { computed, ref } from 'vue';
import { dateTime, tone } from '../lib/ui';
const props = defineProps({ calls: { type: Array, default: () => [] }, error: String });
defineEmits(["retry"]);
const statusName = value => ({ success: "成功", blocked: "被拒绝", failed: "失败", unavailable: "不可用",
  running: "执行中", pending: "执行中", cancelled: "已取消", fallback: "已换路", pending_approval: "等待审批" }[value] || value);
const query = ref(''), filter = ref('');
const statuses = computed(() => [...new Set(props.calls.map(call => call.status).filter(Boolean))]);
const matching = computed(() => {
  const keyword = query.value.trim().toLowerCase();
  return props.calls.filter(call => (!filter.value || call.status === filter.value) &&
    [call.step, call.tool, call.call_id].some(value => (value || '').toLowerCase().includes(keyword)));
});
function clear() { query.value = ''; filter.value = ''; }
</script>

<template>
  <section aria-label="逐次工具调用" class="tool-ledger">
    <h3>逐次工具调用 <span v-if="!error">{{ calls.length }}</span></h3>
    <div v-if="error" role="alert">工具记录读取失败{{ calls.length ? '，下方保留上次记录' : '' }}：{{ error }} <button class="text-button" @click="$emit('retry')">重读工具记录</button></div>
    <p v-else-if="!calls.length">本轮尚无调用记录。</p>
    <div v-if="calls.length > 1 || query || filter" class="ledger-filters">
      <input v-model="query" type="search" aria-label="筛选工具调用" placeholder="按步骤、工具或调用编号筛选" />
      <select v-model="filter" aria-label="调用状态"><option value="">全部状态</option><option v-for="status in statuses" :key="status" :value="status">{{ statusName(status) }}</option></select>
      <span v-if="query.trim() || filter" class="muted" role="status">匹配 {{ matching.length }} 条</span>
      <button v-if="query || filter" class="text-button" @click="clear">清除筛选</button>
    </div>
    <p v-if="calls.length && !matching.length" class="muted">没有匹配的工具调用。</p>
    <details v-for="call in matching" :key="call.call_id">
      <summary><span class="ledger-row"><strong>{{ call.step || '准备排查' }}</strong><code>{{ call.tool || '未记录工具' }}</code>
        <span :class="['status', tone(call.status)]">{{ statusName(call.status) || '状态未记录' }}</span>
        <span class="muted">{{ call.elapsed_ms == null ? '—' : call.elapsed_ms + ' ms' }}</span></span></summary>
      <p v-if="call.reason">原因：{{ call.reason }}</p>
      <p>开始：{{ call.started_at ? dateTime(call.started_at) : '未记录' }} · 结束：{{ call.completed_at ? dateTime(call.completed_at) : '未记录' }}</p>
      <h4>提议与实际参数（已脱敏）</h4><pre>{{ call.arguments == null ? '未记录参数' : JSON.stringify(call.arguments, null, 2) }}</pre>
      <h4>返回结果（已脱敏）</h4><pre>{{ call.result || '未记录结果' }}</pre>
      <p v-if="call.result_truncated" role="note">结果已截断；完整原文是否可读，以本轮证据记录为准。</p>
      <small>调用编号：{{ call.call_id }} · 步骤：{{ call.step_index ?? '未记录' }}</small>
    </details>
  </section>
</template>

<style scoped>
.tool-ledger { margin-top: 24px; border-top: 1px solid var(--line); padding-top: 16px; }
.tool-ledger details { border-bottom: 1px solid var(--line); padding: 12px 0; }
.tool-ledger summary { cursor: pointer; overflow-wrap: anywhere; }
.ledger-row { display: inline-grid; vertical-align: middle; width: calc(100% - 24px); grid-template-columns: minmax(0, 2fr) minmax(0, 1.5fr) minmax(72px, .65fr) 75px; gap: 8px; align-items: baseline; }
.ledger-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 12px 0; }
.ledger-filters input, .ledger-filters select { min-height: 36px; border: 1px solid var(--line); padding: 0 8px; background: white; font: inherit; }
.ledger-filters input { width: min(280px, 100%); }
@media (max-width: 760px) { .ledger-row { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } }
.tool-ledger pre { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.tool-ledger small, .tool-ledger p { color: var(--muted); }
</style>
