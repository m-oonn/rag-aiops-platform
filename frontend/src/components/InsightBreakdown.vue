<script setup>
import { computed } from 'vue';
import Icon from './Icon.vue';
const props = defineProps({
  title: String, description: String, icon: { type: String, default: 'chart' },
  items: { type: Array, required: true }, modelValue: { type: [String, Number], default: '' },
  variant: { type: String, default: 'bars' }, unit: { type: String, default: '项' },
  links: Boolean,
});
const emit = defineEmits(['update:modelValue']);
const max = computed(() => Math.max(1, ...props.items.map(item => item.count)));
const populated = computed(() => props.items.filter(item => item.count > 0));
</script>
<template>
  <section v-if="items.length" class="insight-card" :class="variant" :aria-label="title">
    <header class="insight-header"><span class="insight-icon"><Icon :name="icon" :size="20" /></span>
      <div><h2>{{ title }}</h2><p>{{ description }}</p></div>
      <button v-if="!links && modelValue !== ''" type="button" class="text-button insight-reset" @click="emit('update:modelValue', '')">清除图表筛选</button>
    </header>
    <div v-if="variant === 'composition' && populated.length" class="insight-track" aria-hidden="true">
      <span v-for="item in populated" :key="item.key" :class="`tone-${item.tone || 'info'}`" :style="{ flexGrow: item.count }"></span>
    </div>
    <div class="insight-items">
      <component v-for="item in items" :key="item.key" :is="links ? 'RouterLink' : 'button'" class="insight-item" :class="`tone-${item.tone || 'info'}`"
        :to="links ? item.to : undefined" :type="links ? undefined : 'button'" :aria-pressed="links ? undefined : modelValue === item.key"
        @click="!links && emit('update:modelValue', item.key === modelValue ? '' : item.key)">
        <span class="insight-label"><span class="insight-dot" aria-hidden="true"></span>{{ item.label }}</span>
        <span v-if="variant === 'bars'" class="insight-bar" aria-hidden="true"><span :style="{ width: `${item.count / max * 100}%` }"></span></span>
        <strong>{{ item.count }} <small>{{ unit }}</small></strong>
      </component>
    </div>
  </section>
</template>
<style scoped>
.insight-card { min-width: 0; margin-bottom: 16px; padding: 16px; border: 1px solid var(--line); border-radius: var(--panel-radius); background: #fff; }
.insight-header { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 12px; }
.insight-header > div { min-width: 0; }
.insight-header h2 { margin: 0; color: var(--text); font-size: 15px; }
.insight-header p { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
.insight-icon { display: grid; place-items: center; flex: none; width: 36px; height: 36px; border-radius: 9px; background: #e9f1fe; color: #265eb3; }
.insight-reset { flex: none; margin-inline-start: auto; align-self: center; font-size: 12px; }
.insight-items { display: grid; gap: 6px; }
.insight-card { --fill: #87a9da; --ink: #274e84; }
.tone-success { --fill: #5ea68e; --ink: #146352; }
.tone-danger { --fill: #d3633e; --ink: #9f3c23; }
.tone-warning { --fill: #d2a14d; --ink: #795011; }
.tone-muted { --fill: #9aaabb; --ink: #47566b; }
.insight-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 6px 12px; text-align: start; padding: 8px 10px; min-width: 0; min-height: 36px; color: var(--text); background: #f6f8fb; border: 1px solid transparent; border-radius: 7px; font-size: 12px; cursor: pointer; text-decoration: none; }
.insight-item:hover, .insight-item[aria-pressed='true'] { border-color: var(--fill); background: #edf4ff; }
.insight-item:focus-visible { outline: 2px solid #275fae; outline-offset: -2px; }
.insight-item strong { white-space: nowrap; color: var(--ink); font-size: 15px; font-variant-numeric: tabular-nums; }
.insight-item small { font-size: 11px; font-weight: normal; }
.insight-label { overflow-wrap: anywhere; }
.insight-dot { display: inline-block; margin-inline-end: 6px; width: 8px; height: 8px; border-radius: 3px; background: var(--fill); }
.bars .insight-items { max-height: 220px; overflow: auto; }
.bars .insight-item { grid-template-columns: minmax(0, 0.55fr) minmax(0, 1fr) auto; }
.insight-bar { min-width: 0; height: 10px; border-radius: 4px; background: #e9eef6; }
.insight-bar > span { display: block; height: 100%; border-radius: inherit; background: var(--fill); }
.composition .insight-items, .stages .insight-items { grid-template-columns: repeat(auto-fit, minmax(min(100%, 155px), 1fr)); }
.insight-track { display: flex; gap: 2px; height: 14px; overflow: hidden; border-radius: 5px; margin-bottom: 10px; }
.insight-track > span { background: var(--fill); }
.stages .insight-item { border-top: 3px solid var(--fill); align-content: center; min-height: 50px; }
.stages .insight-dot { display: none; }
@media (max-width: 540px) {
  .insight-header { flex-wrap: wrap; }
  .insight-header > div { flex: 1; }
  .insight-reset { margin-inline-start: 46px; }
  .bars .insight-item { gap: 6px; }
}
</style>
