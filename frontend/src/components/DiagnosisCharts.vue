<script setup>
import { computed } from 'vue';
import { clockTime } from '../lib/diagnosisVisuals';
import Icon from './Icon.vue';

const props = defineProps({ groups: { type: Array, required: true }, records: { type: Array, required: true } });
const emit = defineEmits(['group', 'evidence']);
const bars = computed(() => props.groups.map(group => ({
  id: group.id, label: group.label, total: group.evidence.length,
  abnormal: group.evidence.filter(row => row.state === 'abnormal').length,
})));
const largestGroup = computed(() => Math.max(1, ...bars.value.map(bar => bar.total)));
const points = computed(() => {
  let count = 0;
  return props.records.map(row => ({ row, count: count += Number(row.state === 'abnormal') }));
});
const totalAbnormal = computed(() => points.value.at(-1)?.count ?? 0);
const interval = computed(() => Math.max(1, Math.ceil(totalAbnormal.value / 3)));
const ticks = computed(() => [3, 2, 1, 0].map(number => number * interval.value));
const plotPoints = computed(() => points.value.map((point, index) => ({ ...point,
  x: points.value.length < 2 ? 50 : index * 100 / (points.value.length - 1),
  y: 100 - point.count * 100 / ticks.value[0],
})));
const line = computed(() => plotPoints.value.map(point => `${point.x},${point.y}`).join(' '));
</script>

<template>
  <section class="diagnosis-charts" aria-label="本次诊断图表">
    <section v-if="bars.length" class="chart-card" aria-label="证据分布柱状图">
      <header class="chart-header">
        <span class="chart-icon"><Icon name="chart" :size="20" /></span>
        <div><h3>证据分布</h3><p>按现场对象统计，点击柱子查看该对象的证据。</p></div>
      </header>
      <div class="chart-legend" aria-hidden="true"><span class="all-key">证据总数</span><span class="abnormal-key">异常数</span></div>
      <div class="bar-list">
        <button v-for="bar in bars" :key="bar.id" type="button" class="bar-row"
          :aria-label="`${bar.label}：${bar.total} 条证据，${bar.abnormal} 条异常，查看明细`" @click="emit('group', bar.id)">
          <span class="bar-label">{{ bar.label }}</span>
          <span class="bar-track" aria-hidden="true">
            <span class="bar-total" :style="{ width: `${bar.total / largestGroup * 100}%` }">
              <span v-if="bar.abnormal" class="bar-abnormal" :style="{ width: `${bar.abnormal / bar.total * 100}%` }"></span>
            </span>
          </span>
          <span class="bar-value" aria-hidden="true"><strong :class="{ abnormal: bar.abnormal }">{{ bar.abnormal }}</strong><span> / {{ bar.total }}</span></span>
        </button>
      </div>
      <p class="bar-guide">右侧数字：异常数 / 证据总数</p>
    </section>

    <section v-if="points.length" class="chart-card" aria-label="异常发现折线图">
      <header class="chart-header">
        <span class="chart-icon trend-icon"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4v16h18M6 15l5-5 4 2 5-6"/><path d="M16 6h4v4"/></svg></span>
        <div><h3>异常发现进程</h3><p>按实际采集顺序累计异常条数，点击圆点查看记录。</p></div>
      </header>
      <div class="line-header"><span>累计异常条数</span><strong>{{ totalAbnormal }} 条</strong></div>
      <div class="line-chart">
        <div class="line-ticks" aria-hidden="true"><span v-for="tick in ticks" :key="tick">{{ tick }}</span></div>
        <div class="line-scroll">
          <div class="line-inner" :style="{ minWidth: `${Math.max(0, points.length - 1) * 24 + 26}px` }">
            <div class="line-plot">
              <div class="line-grid" aria-hidden="true"><span v-for="tick in ticks" :key="tick"></span></div>
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                <polygon v-if="points.length > 1" :points="`0,100 ${line} 100,100`" />
                <polyline v-if="points.length > 1" :points="line" vector-effect="non-scaling-stroke" />
              </svg>
              <button v-for="point in plotPoints" :key="point.row.id" type="button" class="line-point"
                :class="{ abnormal: point.row.state === 'abnormal' }" :style="{ left: `${point.x}%`, top: `${point.y}%` }"
                :title="`${point.row.label} · ${point.row.title} · ${point.row.stateLabel} · ${clockTime(point.row.time)}`"
                :aria-label="`${point.row.label}：${point.row.title}，${point.row.stateLabel}，累计 ${point.count} 条异常，查看明细`"
                @click="emit('evidence', point.row.id)"></button>
            </div>
            <div class="line-labels" aria-hidden="true"><span>{{ records[0].label }}</span><span v-if="points.length > 1">{{ records.at(-1).label }}</span></div>
          </div>
        </div>
      </div>
      <p class="bar-guide">横轴：证据采集顺序，不代表实际时间间隔。</p>
    </section>
  </section>
</template>

<style scoped>
.diagnosis-charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }
.chart-card { min-width: 0; padding: 16px; border: 1px solid var(--line); border-radius: var(--panel-radius); background: #fff; }
.chart-header { display: flex; align-items: flex-start; gap: 10px; }
.chart-header h3 { margin: 0; }
.chart-header p { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
.chart-icon { flex: none; display: grid; place-items: center; width: 36px; height: 36px; border-radius: 9px; background: #e9f1fe; color: #265eb3; }
.trend-icon { background: #e4f6f1; color: #08786a; }
.chart-legend, .line-header { display: flex; gap: 16px; align-items: center; margin: 14px 0 7px; color: var(--muted); font-size: 12px; }
.chart-legend span { display: inline-flex; align-items: center; gap: 6px; }
.chart-legend span::before { content: ''; width: 10px; height: 10px; border-radius: 3px; background: #92baff; }
.chart-legend .abnormal-key::before { background: #d3633e; }
.bar-list { display: grid; gap: 2px; max-height: 174px; overflow: auto; padding: 2px 3px; }
.bar-row { display: grid; grid-template-columns: minmax(76px, 0.68fr) minmax(20px, 1fr) auto; align-items: center; text-align: start; gap: 8px; width: 100%; min-height: 34px; padding: 4px 5px; border: 0; border-radius: 6px; background: transparent; color: var(--text); cursor: pointer; font-size: 12px; }
.bar-row:hover, .bar-row:focus-visible { background: #eff5ff; }
.bar-row:focus-visible { outline: 2px solid #265eb3; outline-offset: -2px; }
.bar-label { overflow-wrap: anywhere; }
.bar-track, .bar-total, .bar-abnormal { display: block; height: 12px; border-radius: 4px; }
.bar-track { background: #f0f4fa; }
.bar-total { background: #92baff; }
.bar-abnormal { background: #d3633e; }
.bar-value { min-width: 34px; color: var(--muted); text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.bar-value strong { color: var(--text); }
.bar-value .abnormal { color: #9f3c23; }
.bar-guide { margin: 6px 0 0; color: var(--muted); font-size: 11px; }
.line-header { justify-content: space-between; margin-bottom: 2px; }
.line-header strong { color: #08786a; font-size: 14px; }
.line-chart { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px; align-items: start; }
.line-ticks { display: flex; flex-direction: column; justify-content: space-between; text-align: right; height: 108px; font-size: 11px; line-height: 12px; color: var(--muted); margin-top: 6px; }
.line-scroll { overflow-x: auto; }
.line-inner { padding: 12px 13px 0; }
.line-plot { height: 96px; position: relative; }
.line-grid, .line-plot svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.line-grid { display: flex; flex-direction: column; justify-content: space-between; }
.line-grid span { border-top: 1px dashed #dce7ef; }
.line-plot polygon { fill: #e6f5f1; }
.line-plot polyline { fill: none; stroke: #147f70; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.line-point { position: absolute; display: grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 0; border-radius: 50%; transform: translate(-50%, -50%); background: transparent; cursor: pointer; }
.line-point::before { content: ''; width: 7px; height: 7px; border: 2px solid #147f70; border-radius: 50%; background: white; }
.line-point.abnormal::before { background: #bd4c2b; border-color: #bd4c2b; }
.line-point:hover, .line-point:focus-visible { z-index: 1; outline: 2px solid #147f70; outline-offset: -3px; background: #def2ec; }
.line-labels { display: flex; justify-content: space-between; margin-top: 12px; color: var(--muted); font-size: 11px; }
@media (max-width: 820px) { .diagnosis-charts { grid-template-columns: minmax(0, 1fr); } }
</style>
