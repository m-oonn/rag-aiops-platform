<script setup>
import {computed, nextTick, onBeforeUnmount, onMounted, ref, watch} from 'vue';
import {Handle, Position, VueFlow, useVueFlow} from '@vue-flow/core';
import {animate} from 'animejs';
import scene from './data/scene.json';

const tab = ref('overview');
const candidateId = ref(scene.leadingId || scene.candidates.at(-2).id);
const evidenceId = ref(scene.evidence.at(-1).id);
const replayStep = ref(scene.evidence.length-1);
const playing = ref(false);
const copied = ref(false);
const compactQuery = window.matchMedia('(max-width: 700px)');
const compact = ref(compactQuery.matches);
const onCompactChange = event => {compact.value=event.matches;refit();};
compactQuery.addEventListener('change',onCompactChange);
const evidenceMap = Object.fromEntries(scene.evidence.map(e=>[e.id,e]));
const candidate = computed(()=>scene.candidates.find(c=>c.id===candidateId.value));
const evidence = computed(()=>evidenceMap[evidenceId.value]);
const current = computed(()=>scene.evidence[replayStep.value]);
const findings = scene.findings.map(f=>evidenceMap[f.id]);
const counts = {supported:scene.candidates.filter(c=>c.status==='supported').length,excluded:scene.candidates.filter(c=>c.status==='excluded').length,unresolved:scene.candidates.filter(c=>c.status==='unresolved').length};
const lifecycle = scene.evidence.at(-1).events;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const {fitView, setViewport} = useVueFlow('candidate-map');
let replayTimer;
let animation;
function stopReplay(){playing.value=false;clearInterval(replayTimer);}
function changeTab(value){stopReplay();tab.value=value;}
function showEvidence(id){stopReplay();evidenceId.value=id;tab.value='evidence';}
function moveTo(index){
  replayStep.value=Math.min(scene.evidence.length-1,Math.max(0,index));
  evidenceId.value=scene.evidence[replayStep.value].id;
  nextTick(()=>{
    if(reducedMotion)return;
    animation?.cancel();
    animation=animate('.replay-detail',{opacity:[0.55,1],translateY:[4,0],duration:200,ease:'outExpo'});
  });
}
function replay(){
  if(playing.value){stopReplay();return;}
  if(replayStep.value===scene.evidence.length-1)moveTo(0);
  playing.value=true;
  replayTimer=setInterval(()=>{
    if(replayStep.value>=scene.evidence.length-1){stopReplay();return;}
    moveTo(replayStep.value+1);
    if(replayStep.value===scene.evidence.length-1)stopReplay();
  },1700);
}
function refit(){if(tab.value==='cause')nextTick(()=>compact.value?setViewport({x:8,y:8,zoom:1},{duration:0}):fitView({padding:0.18,duration:reducedMotion?0:180}));}
watch(candidateId,refit);
onBeforeUnmount(()=>{stopReplay();animation?.cancel();compactQuery.removeEventListener('change',onCompactChange);});
onMounted(()=>{
  if(!reducedMotion) animation=animate('.topology-line',{strokeDashoffset:[500,0],duration:220,ease:'outExpo'});
});
async function copyExcerpt(){
  try{await navigator.clipboard.writeText(JSON.stringify(evidence.value.excerpt,null,2));copied.value=true;setTimeout(()=>copied.value=false,1800);}catch{copied.value=false;}
}
const nodes = computed(()=>{
  const records=candidate.value.related.map(id=>evidenceMap[id]);
  return [...records.map((record,index)=>({id:record.id,type:'evidence',position:{x:20,y:index*(compact.value?156:112)+20},data:{record}})),{id:candidate.value.id,type:'candidate',position:compact.value?{x:20,y:records.length*156+25}:{x:380,y:Math.max(25,(records.length-1)*56)},data:{candidate:candidate.value}}];
});
const edges = computed(()=>candidate.value.related.map(id=>{
  const direct=candidate.value.direct.includes(id);
  const relation=direct?candidate.value.relation:'neutral';
  return {id:`${id}-${candidate.value.id}`,source:id,target:candidate.value.id,type:'smoothstep',label:relation==='support'?'支持观察':relation==='contradict'?'反驳解释':'相关记录',style:{stroke:relation==='contradict'?'#b13438':relation==='support'?'#16805c':'#8c969c',strokeWidth:1.5,strokeDasharray:relation==='neutral'?'4 5':undefined},labelBgStyle:{fill:'#f8fafb'},labelStyle:{fill:'#596570',fontSize:12}};
}));
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <a href="#" class="brand" aria-label="AIOps 诊断工作台" @click.prevent="changeTab('overview')"><svg viewBox="0 0 28 28" aria-hidden="true"><path d="M3 21 11 5h6l8 16M7 15h14M11 21l3-6 3 6"/></svg><strong>AIOps</strong><span>诊断工作台</span></a>
      <span class="preview-label">隔离设计预览</span>
      <span class="record-date">{{scene.date}} <span>01:07 UTC</span></span>
    </header>
    <main>
      <div class="report-meta"><span>edge /api/availability</span><span class="completed"><i/>诊断已完成</span></div>
      <div class="report-title"><h1>故障定位到 downstream</h1><span class="report-level">根因待确认</span></div>
      <p class="report-description">端口 4634 无监听；localapp 可连接，但业务请求返回 503。</p>
      <div class="finding-strip">
        <button v-for="item in findings" :key="item.id" @click="showEvidence(item.id)"><span>{{item.subject}}</span><strong>{{item.title}}</strong><span class="finding-source">{{item.code}}<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 4 6 6-6 6"/></svg></span></button>
      </div>
      <nav class="view-tabs" aria-label="报告内容" role="tablist">
        <button id="tab-overview" role="tab" :aria-selected="tab==='overview'" aria-controls="panel-overview" @click="changeTab('overview')">报告总览</button>
        <button id="tab-cause" role="tab" :aria-selected="tab==='cause'" aria-controls="panel-cause" @click="changeTab('cause')">候选原因 <span>{{scene.candidates.length}}</span></button>
        <button id="tab-evidence" role="tab" :aria-selected="tab==='evidence'" aria-controls="panel-evidence" @click="changeTab('evidence')">现场证据 <span>{{scene.evidence.length}}</span></button>
        <button id="tab-process" role="tab" :aria-selected="tab==='process'" aria-controls="panel-process" @click="changeTab('process')">排查过程</button>
      </nav>
      <section v-if="tab==='overview'" id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" class="overview">
        <div class="section-heading"><h2>异常在哪里</h2><span>依赖关系与本轮观测</span></div>
        <div class="topology" aria-label="服务依赖图：edge 到 localapp，再到 downstream。异常传播关系未确认。">
          <div class="service-spot"><span class="service-symbol"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v12H4zM9 21h6m-3-4v4M8 9h8m-8 4h5"/></svg></span><strong>edge</strong><span>请求入口</span><small>端口 4632</small></div>
          <div class="connection"><svg viewBox="0 0 200 28" preserveAspectRatio="none" aria-hidden="true"><path class="topology-line" d="M0 14H198"/><path d="m190 8 8 6-8 6"/></svg><span>登记依赖</span></div>
          <button class="service-spot affected" @click="showEvidence(scene.evidence[8].id)"><span class="service-symbol"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3h14v18H5zM8 7h8m-8 5h8m-8 5h4"/></svg></span><strong>localapp</strong><span>HTTP 503</span><small>端口 4633 · TCP 可达</small></button>
          <div class="connection failed"><svg viewBox="0 0 200 28" preserveAspectRatio="none" aria-hidden="true"><path class="topology-line" d="M0 14H85M115 14H198"/><path d="m94 8 12 12m0-12L94 20m96-12 8 6-8 6"/></svg><span>日志：连接未建立</span></div>
          <button class="service-spot fault" @click="showEvidence(scene.evidence[7].id)"><span class="service-symbol"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16v6H4zM4 14h16v6H4zM7 7h1m-1 10h1m7-10h2m-2 10h2"/></svg></span><strong>downstream</strong><span>无匹配进程 · 无监听</span><small>端口 4634</small></button>
        </div>
        <div class="overview-split">
          <section class="lifecycle-section"><div class="section-heading"><h2>退出前发生了什么</h2><button class="text-button" @click="showEvidence(scene.evidence[9].id)">查看日志 <span>E10</span></button></div><ol class="lifecycle"><li v-for="event in lifecycle" :key="event.code"><span class="event-dot"/><time>{{event.time}}</time><strong>{{event.label}}</strong><span>{{event.detail}}</span></li></ol><p class="unresolved-line"><span class="status-dot unresolved"/>停止请求的发起者未知，完整异常传播关系尚未确认。</p></section>
          <section class="next-section"><div class="section-heading"><h2>下一步核实</h2><span>建议待人工处理</span></div><ol class="next-actions"><li><span>01</span><div><strong>复核 downstream 当前状态</strong><p>确认服务仍无进程与监听后，按既有方式恢复。</p></div><button class="text-button" @click="showEvidence(scene.evidence[3].id)">依据 E04</button></li><li><span>02</span><div><strong>复测入口业务请求</strong><p>恢复后核对 HTTP 状态，再查看 localapp 日志。</p></div><button class="text-button" @click="showEvidence(scene.evidence[8].id)">依据 E09</button></li></ol></section>
        </div>
        <div class="candidate-summary"><div><strong>{{counts.unresolved}} 项解释仍待验证</strong><span>{{counts.supported}} 项现场条件有支持 · {{counts.excluded}} 项解释已排除</span></div><button class="outline-button" @click="changeTab('cause')">检查候选原因 <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 10h14m-6-6 6 6-6 6"/></svg></button></div>
      </section>
      <section v-else-if="tab==='cause'" id="panel-cause" role="tabpanel" aria-labelledby="tab-cause" class="cause-workspace">
        <div class="compact-picker"><label for="candidate-select">切换候选</label><select id="candidate-select" v-model="candidateId"><option v-for="item in scene.candidates" :key="item.id" :value="item.id">{{item.code}} · {{item.title}} · {{item.statusLabel}}</option></select></div>
        <aside class="candidate-list" aria-label="候选原因列表"><button v-for="item in scene.candidates" :key="item.id" :aria-pressed="candidateId===item.id" @click="candidateId=item.id"><span class="candidate-code">{{item.code}}</span><span class="candidate-content"><strong>{{item.title}}</strong><span>{{item.type}}<span :class="['status-text',item.status]"><i/>{{item.statusLabel}}</span></span></span></button></aside>
        <div class="candidate-main"><div class="candidate-heading"><h2>{{candidate.title}}</h2><span :class="['status-text',candidate.status]"><i/>{{candidate.statusLabel}}</span></div>
          <div class="relation-map" :style="compact?{height:((candidate.related.length+1)*150+40)+'px'}:undefined"><VueFlow id="candidate-map" :nodes="nodes" :edges="edges" :nodes-draggable="false" :nodes-connectable="false" :zoom-on-scroll="false" :pan-on-drag="false" :min-zoom="0.3" :max-zoom="1" @nodes-initialized="refit">
            <template #node-evidence="{data}"><button class="evidence-node" @click.stop="showEvidence(data.record.id)"><span>{{data.record.code}} · {{data.record.kindLabel}}</span><strong>{{data.record.subject}}</strong><span>{{data.record.title}}</span><Handle type="source" :position="Position.Right"/></button></template>
            <template #node-candidate="{data}"><div class="candidate-node"><Handle type="target" :position="compact?Position.Right:Position.Left"/><span>{{data.candidate.code}} · {{data.candidate.type}}</span><strong>{{data.candidate.title}}</strong><span :class="['status-text',data.candidate.status]">{{data.candidate.statusLabel}}</span></div></template>
          </VueFlow><div class="map-legend"><span><i/>支持 / 反驳</span><span><i class="dashed"/>相关记录</span></div></div>
          <div class="candidate-note"><h3>当前判断</h3><p>{{candidate.note}}</p></div>
          <details class="original-explanation"><summary>查看完整解释</summary><p>{{candidate.explanation}}</p></details>
        </div>
        <aside class="related-evidence"><h3>关联证据 <span>{{candidate.related.length}}</span></h3><button v-for="id in candidate.related" :key="id" @click="showEvidence(id)"><span>{{evidenceMap[id].code}} · {{evidenceMap[id].kindLabel}}</span><strong>{{evidenceMap[id].subject}}</strong><span>{{evidenceMap[id].title}}</span><time>{{evidenceMap[id].time}} UTC</time></button></aside>
      </section>
      <section v-else-if="tab==='evidence'" id="panel-evidence" role="tabpanel" aria-labelledby="tab-evidence" class="evidence-workspace">
        <div class="compact-picker"><label for="evidence-select">切换证据</label><select id="evidence-select" v-model="evidenceId"><option v-for="item in scene.evidence" :key="item.id" :value="item.id">{{item.code}} · {{item.subject}} · {{item.kindLabel}}</option></select></div>
        <aside class="evidence-list" aria-label="现场证据列表"><button v-for="item in scene.evidence" :key="item.id" :aria-pressed="evidenceId===item.id" @click="evidenceId=item.id"><span class="evidence-index">{{item.code}}</span><span><strong>{{item.subject}}</strong><span>{{item.kindLabel}}</span></span><time>{{item.time}}</time></button></aside>
        <article class="evidence-detail"><div class="evidence-heading"><h2>{{evidence.subject}}</h2><span>{{evidence.code}} · {{evidence.kindLabel}} · {{evidence.time}} UTC</span></div><p class="evidence-conclusion">{{evidence.title}}</p><dl class="evidence-fields"><template v-for="field in evidence.fields" :key="field[0]"><dt>{{field[0]}}</dt><dd>{{field[1]}}</dd></template></dl><ol v-if="evidence.events.length" class="event-timeline"><li v-for="event in evidence.events" :key="event.at"><time>{{event.time}}</time><div><strong>{{event.label}}</strong><span>{{event.detail}}</span></div></li></ol>
          <details class="excerpt"><summary>查看已保存字段节选</summary><div class="excerpt-toolbar"><span>Probe 采集记录</span><button class="text-button" @click="copyExcerpt">{{copied?'已复制':'复制节选'}}</button></div><pre>{{JSON.stringify(evidence.excerpt,null,2)}}</pre></details>
        </article>
      </section>
      <section v-else id="panel-process" role="tabpanel" aria-labelledby="tab-process" class="process-workspace">
        <div class="process-heading"><div><h2>现场采集回放</h2><span>01:07:09 — 01:07:50 UTC · {{scene.evidence.length}} 项记录</span></div><div class="replay-controls"><button class="icon-button" aria-label="上一项" :disabled="replayStep===0" @click="stopReplay();moveTo(replayStep-1)"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12 4-6 6 6 6"/></svg></button><button class="primary-button" @click="replay"><svg viewBox="0 0 20 20" aria-hidden="true"><path v-if="playing" d="M7 4v12m6-12v12"/><path v-else d="m6 3 10 7-10 7Z"/></svg>{{playing?'暂停回放':'播放回放'}}</button><button class="icon-button" aria-label="下一项" :disabled="replayStep===scene.evidence.length-1" @click="stopReplay();moveTo(replayStep+1)"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m8 4 6 6-6 6"/></svg></button></div></div>
        <div class="replay-progress"><span>{{current.code}}</span><input aria-label="采集进度" type="range" min="0" :max="scene.evidence.length-1" :value="replayStep" @input="stopReplay();moveTo(Number($event.target.value))"><span>{{scene.evidence.length}} 项</span></div>
        <div class="replay-workspace"><ol class="collection-list"><li v-for="(item,index) in scene.evidence" :key="item.id"><button :class="{passed:index<replayStep,current:index===replayStep}" :aria-current="index===replayStep?'step':undefined" @click="stopReplay();moveTo(index)"><time>{{item.time}}</time><span class="collection-dot"/><span><strong>{{item.subject}}</strong><span>{{item.kindLabel}}</span></span><span>{{item.code}}</span></button></li></ol><div class="replay-detail" aria-live="polite"><div class="replay-record-head"><h3>{{current.subject}}</h3><span>{{current.code}} · {{current.time}} UTC</span></div><p>{{current.title}}</p><ol v-if="current.events.length" class="event-timeline"><li v-for="event in current.events" :key="event.at"><time>{{event.time}}</time><div><strong>{{event.label}}</strong><span>{{event.detail}}</span></div></li></ol><dl v-else class="evidence-fields"><template v-for="field in current.fields" :key="field[0]"><dt>{{field[0]}}</dt><dd>{{field[1]}}</dd></template></dl><button class="text-button" @click="showEvidence(current.id)">查看证据详情 <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 10h14m-6-6 6 6-6 6"/></svg></button></div></div>
      </section>
      <footer><span>保存现场 · {{scene.date}} · UTC</span><span>原始诊断：故障层定位，根因未确认</span></footer>
    </main>
  </div>
</template>
