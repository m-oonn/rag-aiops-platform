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
  observer = new ResizeObserver(entries => { if (entries[0].contentRect.width) width.value = entries[0].contentRect.width; });
  observer.observe(canvas.value);
});
onUnmounted(() => observer?.disconnect());
const layers = computed(() => {
  if (!props.graph.edges.length) {
    const count = Math.max(1, Math.floor(width.value / 166));
    return props.graph.nodes.reduce((columns, node, i) => {
      (columns[i % count] ||= []).push(node.id);
      return columns;
    }, []);
  }
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
    rows.push(ids);
  }
  return rows;
});
const horizontal = computed(() => width.value >= 360 && width.value >= layers.value.length * 166);
const lanes = computed(() => horizontal.value ? layers.value : layers.value.flatMap(row => {
  const perRow = width.value < 320 ? 1 : 2;
  return row.reduce((chunks, id, i) => {
    if (i % perRow === 0) chunks.push([]);
    chunks.at(-1).push(id);
    return chunks;
  }, []);
}));
const height = computed(() => 20 + (horizontal.value
  ? Math.max(1, ...lanes.value.map(row => row.length)) * 94 : lanes.value.length * 94));
const points = computed(() => Object.fromEntries(lanes.value.flatMap((row, level) => row.map((id, index) => [id, horizontal.value ? {
  x: (level + 0.5) * width.value / lanes.value.length, y: (index + 0.5) * height.value / row.length,
} : { x: (index + 0.5) * width.value / row.length, y: 10 + (level + 0.5) * 94 }]))));
const relationPaths = computed(() => props.graph.edges.flatMap(edge => {
  const from = points.value[edge.from], to = points.value[edge.to];
  if (!from || !to) return [];
  const start = horizontal.value ? from.x : from.y, end = horizontal.value ? to.x : to.y;
  const mid = (start + end) / 2;
  return [{ ...edge, path: horizontal.value
    ? `M${from.x},${from.y} H${mid} V${to.y} H${to.x}`
    : `M${from.x},${from.y} V${mid} H${to.x} V${to.y}` }];
}));
function state(node) {
  const rows = node.evidence;
  return rows.some((row) => row.state === "abnormal") ? "存在异常观测" : node.evidence.length ? `${node.evidence.length} 项观测` : "尚无观测";
}
function nodeLabel(node) { return node.label || serviceLabel(node.service || node.id); }
function edgeLabel(id) {
  const node = props.graph.nodes.find((item) => item.id === id);
  return nodeLabel(node || { id });
}
</script>
<template>
  <div ref="canvas" class="diagnostic-topology" aria-label="服务与现场观测">
    <div v-if="!graph.nodes.length" class="empty-state">取得服务观测后显示关系图</div>
    <template v-else>
      <div class="topology-canvas" :style="{ height: `${height}px` }">
        <svg :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none" aria-hidden="true">
          <path v-for="edge in relationPaths" :key="`${edge.from}-${edge.to}`" :d="edge.path" />
        </svg>
        <button v-for="node in graph.nodes" :key="node.id" type="button"
          :class="['topology-node', { selected: node.id === selected, abnormal: node.evidence.some(row => row.state === 'abnormal'), current: node.evidence.some(row => row.id === current) }]"
          :style="{ left: `${points[node.id].x / width * 100}%`, top: `${points[node.id].y / height * 100}%` }"
          :title="nodeLabel(node)" :aria-pressed="node.id === selected" @click="$emit('select', node.id)">
          <span class="node-symbol"><Icon name="server" :size="24" /></span>
          <span class="node-details"><strong>{{ nodeLabel(node) }}</strong><small>{{ state(node) }}</small></span>
        </button>
      </div>
      <div v-if="graph.edges.length" class="topology-relations">
        <button v-for="edge in graph.edges" :key="`${edge.from}-${edge.to}`" class="text-button" @click="$emit('evidence', edge.evidence)">
          {{ edgeLabel(edge.from) }} → {{ edgeLabel(edge.to) }}<span>{{ edge.label }}</span>
        </button>
      </div>
    </template>
  </div>
</template>
<style scoped>
.diagnostic-topology { min-width: 0; padding: 12px 0; }
.topology-canvas { position: relative; width: 100%; border-radius: var(--control-radius); background: radial-gradient(#c8d6e7 1px, transparent 1px) 0 0 / 16px 16px, var(--surface); }
.topology-canvas > svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
path { fill: none; stroke: #778da7; stroke-width: 1.5; stroke-dasharray: 4 4; }
.topology-node { position: absolute; transform: translate(-50%, -50%); width: 144px; max-width: 90%; min-height: 59px; padding: 8px; display: flex; align-items: center; gap: 7px; text-align: left; border: 1px solid var(--line); border-radius: var(--control-radius); background: #fff; color: var(--text); box-shadow: 0 2px 6px #182d4910; }
.topology-node:hover, .topology-node.selected, .topology-node.current { border-color: var(--blue); }
.topology-node.selected, .topology-node.current { background: var(--accent-soft); }
.node-symbol { flex: none; display: grid; place-items: center; width: 29px; height: 29px; border-radius: 7px; background: #edf3fa; color: var(--blue); }
.node-symbol svg { width: 18px; height: 18px; }
.node-details { min-width: 0; display: grid; gap: 2px; }
.node-details strong { font-size: 12px; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-details small { font-size: 11px; color: var(--muted); }
.abnormal .node-symbol { color: var(--danger); background: #fff1ed; }
.abnormal small { color: var(--danger); }
.topology-relations { display: flex; flex-wrap: wrap; gap: 6px 12px; padding-top: 8px; }
.topology-relations button { display: inline-flex; justify-content: flex-start; white-space: normal; text-align: left; font-size: 12px; flex-wrap: wrap; gap: 4px 8px; overflow-wrap: anywhere; }
.topology-relations span { color: var(--muted); }
</style>
