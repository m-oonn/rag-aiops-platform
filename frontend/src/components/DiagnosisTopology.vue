<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import Icon from "./Icon.vue";
import { serviceLabel } from "../lib/diagnosisVisuals";
const props = defineProps({ graph: { type: Object, required: true }, selected: String, current: String });
defineEmits(["select", "evidence"]);
const canvas = ref(null), width = ref(900);
let observer;
onMounted(() => {
  if (typeof ResizeObserver === "undefined") return;
  observer = new ResizeObserver(entries => { width.value = entries[0].contentRect.width; });
  observer.observe(canvas.value);
});
onUnmounted(() => observer?.disconnect());
const columns = computed(() => Math.min(props.graph.nodes.length, width.value < 480 ? 2 : 4) || 1);
const layers = computed(() => {
  const remaining = new Set(props.graph.nodes.map(node => node.id)), depth = new Map();
  while (remaining.size) {
    const ready = [...remaining].filter(id => props.graph.edges.filter(edge => edge.to === id)
      .every(edge => depth.has(edge.from)));
    if (!ready.length) { for (const id of remaining) depth.set(id, 0); break; }
    for (const id of ready) {
      depth.set(id, Math.max(0, ...props.graph.edges.filter(edge => edge.to === id).map(edge => depth.get(edge.from) + 1)));
      remaining.delete(id);
    }
  }
  const rows = [];
  for (const level of [...new Set(depth.values())].sort((a, b) => a - b)) {
    const ids = props.graph.nodes.filter(node => depth.get(node.id) === level).map(node => node.id);
    for (let i = 0; i < ids.length; i += columns.value) rows.push(ids.slice(i, i + columns.value));
  }
  return rows;
});
const height = computed(() => layers.value.length * 180 + 40);
const points = computed(() => Object.fromEntries(layers.value.flatMap((row, level) => row.map((id, index) => [id, {
  x: (index + 0.5) * 900 / row.length, y: level * 180 + 90,
}]))));
function state(node) {
  const rows = node.evidence;
  return rows.some((row) => row.state === "abnormal") ? "存在异常观测" : node.evidence.length ? `${node.evidence.length} 项观测` : "尚无观测";
}
</script>
<template>
  <div ref="canvas" class="diagnostic-topology" aria-label="服务与现场观测">
    <div v-if="!graph.nodes.length" class="empty-state">取得服务观测后显示关系图</div>
    <template v-else>
      <div class="topology-canvas" :style="{ aspectRatio: `900 / ${height}`, minHeight: `${Math.ceil(graph.nodes.length / columns) * 156}px` }">
        <svg :viewBox="`0 0 900 ${height}`" preserveAspectRatio="none" aria-hidden="true">
          <path v-for="edge in graph.edges" :key="`${edge.from}-${edge.to}`"
            :d="`M${points[edge.from].x},${points[edge.from].y} L${points[edge.to].x},${points[edge.to].y}`" />
        </svg>
        <button v-for="node in graph.nodes" :key="node.id" type="button"
          :class="['topology-node', { selected: node.id === selected, current: node.evidence.some(row => row.id === current) }]"
          :style="{ left: `${points[node.id].x / 9}%`, top: `${points[node.id].y / height * 100}%` }"
          :aria-pressed="node.id === selected" @click="$emit('select', node.id)">
          <span class="node-symbol"><Icon name="server" :size="24" /></span>
          <strong>{{ serviceLabel(node.id) }}</strong>
          <small :class="{ 'observation-alert': node.evidence.some(row => row.state === 'abnormal') }">{{ state(node) }}</small>
        </button>
      </div>
      <div v-if="graph.edges.length" class="topology-relations">
        <button v-for="edge in graph.edges" :key="`${edge.from}-${edge.to}`" class="text-button" @click="$emit('evidence', edge.evidence)">
          {{ serviceLabel(edge.from) }} → {{ serviceLabel(edge.to) }}<span>{{ edge.label }}</span>
        </button>
      </div>
    </template>
  </div>
</template>
<style scoped>
.diagnostic-topology { min-width: 0; padding: 16px 0; }
.topology-canvas { position: relative; width: 100%; min-width: 0; background: radial-gradient(#dfdfdd .8px, transparent .8px) 0 0 / 18px 18px; }
.topology-canvas > svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
path { fill: none; stroke: #b9b9b6; stroke-width: 1.5; stroke-dasharray: 6 6; vector-effect: non-scaling-stroke; }
.topology-node { position: absolute; transform: translate(-50%, -36px); width: 130px; max-width: 45%; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 0; border: 0; background: transparent; color: #323130; cursor: pointer; font: inherit; }
.node-symbol { display: grid; place-items: center; width: 64px; height: 64px; border: 1px solid #d1d1ce; border-radius: 50%; background: #fff; transition: background 180ms, border-color 180ms; color: #605e5c; }
.topology-node.selected .node-symbol, .topology-node.current .node-symbol { border: 2px solid #0078d4; color: #0078d4; background: #eff6fc; }
.topology-node.current .node-symbol { outline: 6px solid #e0effb; }
.topology-node strong { font-weight: 600; font-size: 14px; overflow-wrap: anywhere; }
.topology-node small, .node-port { font-size: 11px; color: #73716e; }
.topology-node small.observation-alert { color: #a4262c; }
.topology-relations { display: flex; flex-direction: column; align-items: flex-start; padding: 12px 0 0; gap: 8px; }
.topology-relations button { white-space: normal; text-align: left; font-size: 12px; flex-wrap: wrap; }
.topology-relations span { color: #73716e; margin-left: 8px; }
@media(max-width:600px) { .topology-node strong { font-size: 12px; } .node-symbol { width: 40px; height: 40px; } .topology-node { transform: translate(-50%, -20px); } }
@media(prefers-reduced-motion:reduce) { .node-symbol { transition: none; } }
</style>
