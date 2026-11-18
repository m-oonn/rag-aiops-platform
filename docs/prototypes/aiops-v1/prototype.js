'use strict';

// Review-only prototype: all scenes are fictional; no product API or model requests.
const icons = {
  pulse: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  history: '<path d="M3 11a9 9 0 1 1 2.6 7M3 4v7h7M12 7v5l3 2"/>',
  book: '<path d="M4 3h14a2 2 0 0 1 2 2v16H6a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3M3 17h17M8 7h7M8 11h5"/>',
  settings: '<path d="m9 3-1 3-3 1-2 3 2 2v3l3 1 1 3h5l1-3 3-1v-3l2-2-2-3-3-1-1-3Z"/><circle cx="11.5" cy="11" r="3"/>',
  code: '<path d="m8 5-6 7 6 7m8-14 6 7-6 7m-3-17-2 20"/>',
  chevron: '<path d="m8 10 4 4 4-4"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  external: '<path d="M14 3h7v7m0-7L11 13M9 3H4v17h17v-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
  play: '<path d="m8 4 12 8-12 8Z"/>',
  copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V3H3v13h5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
  network: '<rect x="8" y="2" width="8" height="6" rx="1"/><rect x="2" y="16" width="7" height="6" rx="1"/><rect x="15" y="16" width="7" height="6" rx="1"/><path d="M12 8v4M5 16v-4h14v4"/>',
  box: '<path d="m12 3 9 5-9 5-9-5Zm-9 5v10l9 5 9-5V8M12 13v10M7 6l10 5"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
  download: '<path d="M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  file: '<path d="M5 2h9l5 5v15H5ZM14 2v6h5M9 13h6M9 17h6"/>',
  terminal: '<path d="m4 6 6 6-6 6m9 0h7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 3"/>',
  warning: '<path d="m12 3 10 18H2ZM12 9v5m0 3v1"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>'
};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const badge = (text, tone = 'neutral') => `<span class="badge ${tone}">${escapeHtml(text)}</span>`;
function hydrateIcons(root = document) { $$('[data-icon]', root).forEach(el => { el.innerHTML = icon(el.dataset.icon); }); }

const evidenceIds = ['ev-demo0000000000000001', 'ev-demo0000000000000002', 'ev-demo0000000000000003', 'ev-demo0000000000000004'];
const sceneData = {
  stopped: {
    id:'demo-stopped-001', date:'11月13日 10:24', query:'入口 edge 持续返回 503，请排查 localapp 与 downstream 的调用链，确认故障原因。', state:'诊断已完成', level:'confirmed_cause', label:'原因已确认', tone:'success', target:'downstream',
    title:'下游服务停止，导致依赖请求失败',
    description:'示例证据链显示：downstream 收到停止请求后退出，localapp 连接该依赖被拒绝，同一请求在 edge 返回 503。',
    reason:'downstream_stopped_after_request',
    advice:'先核对 downstream 停止操作的来源和维护安排；经人工确认后恢复服务，再复测 localapp 与 edge 的业务请求。',
    limitation:'停止发起者与更深层历史原因尚未查明。以上为界面演示构造的证据，不是实际诊断结论。',
    findings:[['停止事件与退出记录相互对应','downstream 的生命周期日志记录 shutdown_requested，进程随后退出。',0],['进程与监听状态支持停止判断','downstream 未见对应进程与端口监听；结果限定于本次采集时刻。',1],['同一请求串联应用失败与入口异常','localapp 连接下游被拒绝，edge 对应请求返回 503。',2]],
    evidence:[
      {kind:'生命周期日志', service:'downstream', tool:'probe_text_log', summary:'停止请求后服务退出', status:'ok', text:'[虚构示例]\n10:23:40 shutdown_requested service=downstream\n10:23:40 shutdown_complete service=downstream pid=21840'},
      {kind:'进程与端口',service:'downstream',tool:'probe_process_snapshot / probe_port_snapshot',summary:'未见对应进程与监听',status:'ok',text:'[虚构示例]\nservice=downstream\nprocess_running=false\nlistener_present=false\n观察仅覆盖采集时刻及配置的业务范围。'},
      {kind:'请求链日志',service:'localapp → edge',tool:'probe_text_log',summary:'相同请求的连接拒绝与 503',status:'ok',text:'[虚构示例]\nlocalapp request_id=demo-request-01 upstream=downstream error_type=ConnectionRefusedError\nedge request_id=demo-request-01 upstream_status=503 response_status=503'},
      {kind:'配置快照',service:'localapp',tool:'probe_config_snapshot',summary:'配置的下游与场景登记一致',status:'ok',text:'[虚构示例]\nservice=localapp\nupstream=downstream\nloaded_config_hash=demo-config-hash\n本条只能说明当前配置，不独立证明因果。'}
    ],
    candidates:[
      {name:'downstream 已停止',status:'支持',tone:'success',support:'停止日志、进程退出和无监听相互印证。',against:'本次尚未取得相反现场证据。',unknown:'停止操作的发起者与业务背景。',ref:0},
      {name:'localapp 使用了错误下游地址',status:'本次未支持',tone:'neutral',support:'连接失败使该解释有检查价值。',against:'当前加载配置与登记的依赖地址一致。',unknown:'更早时段的配置历史不在本次覆盖范围。',ref:3},
      {name:'edge 自身处理异常',status:'本次未支持',tone:'neutral',support:'入口存在 503 表现。',against:'同请求已有 localapp 的依赖失败记录。',unknown:'未将一次请求观察外推为 edge 始终正常。',ref:2}
    ]
  },
  config: {
    id:'demo-config-002',date:'11月13日 09:48',query:'localapp 启动后持续失败，近期改过配置，请核对配置与请求失败之间的关系。',state:'诊断已完成',level:'localized_fault',label:'已定位 · 原因待核实',tone:'warning',target:'localapp',
    title:'异常定位到 localapp，配置原因仍待核实',description:'配置值与失败日志已被观察到，但现有示例证据不能证明该值被应用拒绝，不能据此确认配置错误导致故障。',reason:'',advice:'补充配置校验结果或明确的拒绝日志，再核对加载配置与失败请求的对应关系。未经核实，不直接建议修改某个值。',limitation:'“存在可疑配置”与“配置导致失败”是不同结论；该场景只演示保留证据缺口的界面。',
    findings:[['应用侧存在失败记录','localapp 在本次观察窗口内返回错误。',0],['已取得当前加载配置','配置快照提供 max_attempts 的值，但未取得应用拒绝该值的直接证据。',1],['下游有响应，仍需核查请求条件','一次依赖探测成功，不能排除特定业务路径的异常。',2]],
    evidence:[{kind:'应用日志',service:'localapp',tool:'probe_text_log',summary:'观察到请求失败',status:'ok',text:'[虚构示例]\nlocalapp request_id=demo-config-request status=500\n未取得可明确解释失败原因的日志字段。'},{kind:'配置快照',service:'localapp',tool:'probe_config_snapshot',summary:'已读取 max_attempts 配置值',status:'ok',text:'[虚构示例]\nmax_attempts=-1\nloaded_config_hash=demo-config-02\n配置存在不等于已证明应用拒绝此值。'},{kind:'依赖探测',service:'downstream',tool:'probe_dependency_probe',summary:'本次探测收到响应',status:'ok',text:'[虚构示例]\nconnection_established=true\nresponse_status=200\n仅覆盖当前探测，不外推为所有请求正常。'},{kind:'配置变更',service:'localapp',tool:'search_changes',summary:'未取得变更记录',status:'unavailable',text:'[虚构示例]\ndata_source=unavailable\n配置变更来源不可用，不能判定没有变更。'}],
    candidates:[{name:'配置值被应用拒绝',status:'待核实',tone:'warning',support:'配置值可疑且应用请求失败。',against:'无足以排除该解释的证据。',unknown:'缺应用校验结果或明确拒绝日志。',ref:1},{name:'应用内部其他错误',status:'待核实',tone:'warning',support:'应用侧返回 500。',against:'现有日志不足以排除。',unknown:'需要更具鉴别力的应用错误上下文。',ref:0},{name:'下游完全不可达',status:'本次未支持',tone:'neutral',support:'应用依赖该下游。',against:'本次探测已取得响应。',unknown:'特定业务请求路径未被覆盖。',ref:2}]
  },
  latency: {
    id:'demo-latency-003',date:'11月12日 16:35',query:'入口响应超时，localapp 的下游连接可以建立，请区分下游慢与应用内部异常。',state:'诊断已完成',level:'localized_fault',label:'已定位 · 原因待核实',tone:'warning',target:'localapp / downstream',
    title:'失败发生在依赖响应阶段，原因尚未确认',description:'已观察到连接建立后等待响应超时。当前示例缺少可比较的下游响应耗时与应用超时阈值证据，保留下游慢与应用侧问题两种解释。',reason:'',advice:'补充相同请求的下游响应耗时、应用超时阈值与时间关联；以新证据区分候选，再决定处置对象。',limitation:'不通过重复使用同一份日志提高可信度，不把连接成功解释为依赖完全正常。',
    findings:[['连接已经建立','依赖连接建立成功，当前证据不支持“端口始终不可达”。',0],['失败出现在等待响应阶段','localapp 记录 TimeoutError，失败位置为 receive_headers。',1],['缺少完成原因判断的比较证据','没有相同请求的下游耗时与已加载超时阈值的完整关联。',2]],
    evidence:[{kind:'连接记录',service:'localapp → downstream',tool:'probe_dependency_probe',summary:'依赖连接建立成功',status:'ok',text:'[虚构示例]\nconnection_established=true\n该事实仅支持连接可建立，不证明业务响应及时。'},{kind:'应用日志',service:'localapp',tool:'probe_text_log',summary:'等待响应头超时',status:'ok',text:'[虚构示例]\nrequest_id=demo-slow-request\nphase=receive_headers\nerror_type=TimeoutError'},{kind:'比较依据',service:'localapp / downstream',tool:'probe_text_log',summary:'关键比较字段缺失',status:'partial',text:'[虚构示例]\n已采集日志不含相同请求的下游完成耗时。\n阈值与加载配置的完整对应关系未取得。\n字段缺失保留未知。'},{kind:'入口日志',service:'edge',tool:'probe_text_log',summary:'入口请求返回错误',status:'ok',text:'[虚构示例]\nrequest_id=demo-slow-request status=503\n入口状态本身不能确定下游慢的原因。'}],
    candidates:[{name:'下游响应超过应用超时阈值',status:'待核实',tone:'warning',support:'连接后等待响应超时。',against:'未取得能排除该解释的证据。',unknown:'缺相同请求下的耗时与阈值比较。',ref:2},{name:'应用自身处理或超时配置异常',status:'待核实',tone:'warning',support:'应用日志出现 TimeoutError。',against:'日志没有明确指向应用内部错误。',unknown:'需要应用配置与请求阶段的进一步证据。',ref:1},{name:'下游服务已经停止',status:'本次未支持',tone:'neutral',support:'入口表现同样可能是 503。',against:'本次依赖连接可建立。',unknown:'不能把有限时刻观测扩展为整个时段。',ref:0}]
  },
  approval: {
    id:'demo-terminal-004',date:'11月13日 10:31',query:'需要补充主机只读检查，请使用受控终端核对服务状态。',state:'等待终端审批',level:'pending_terminal_approval',label:'等待人工审批',tone:'blue',target:'localapp',title:'补充检查已准备，等待人工审批',description:'Agent 提出了只读服务状态检查。命令尚未执行，不能将预期结果写入诊断依据。',reason:'',advice:'正式运行时前往服务器返回的 Termcp 地址核对命令、目标和有效期；审批后回到此处核验并续跑。',limitation:'本原型没有连接 Termcp，没有真实待审批会话；页面按钮仅解释正式流程。',findings:[['检查命令已提出，尚未执行','命令：Get-Service -Name localapp；此处仅用于展示待审批状态。',0]],evidence:[{kind:'当前观察',service:'localapp',tool:'probe_service_status',summary:'服务状态信息不完整',status:'partial',text:'[虚构示例]\n未取得足以完成判断的服务状态字段。\n补充终端命令尚未执行。'}],candidates:[{name:'localapp 服务状态异常',status:'待核实',tone:'warning',support:'现有服务信息不完整。',against:'尚未取得补充命令结果。',unknown:'需核验终端审批后实际执行结果。',ref:0}]
  },
  failed: {
    id:'demo-failed-005',date:'11月13日 10:36',query:'入口服务不可用，请尝试收集现场证据并定位。',state:'诊断执行失败',level:'failed',label:'未形成诊断结论',tone:'danger',target:'尚未定位',title:'本次诊断中断，未形成可支持的结论',description:'示例中模型请求失败，流程未完成。失败前取得的观察仍可查看，但不能把部分过程呈现为已完成诊断。',reason:'',advice:'保留诊断 ID 与已采集证据，先核对依赖可用性和请求失败原因。若重新发起，应作为新诊断并明确可能再次产生费用。',limitation:'原型不提供不存在的重试接口，也不自动续发模型请求。',findings:[['已保存初步现场观察','仅覆盖一个采集时刻，尚不足以定位。',0]],evidence:[{kind:'初步观察',service:'edge',tool:'probe_text_log',summary:'观察到入口错误，缺后续证据',status:'partial',text:'[虚构示例]\nedge response_status=503\n后续诊断未完成；没有原因结论。'}],candidates:[]
  }
};
const sources = [{name:'主机 Probe',icon:'terminal',status:'available',text:'可用'},{name:'日志检索',icon:'file',status:'unavailable',text:'不可用'},{name:'监控指标',icon:'pulse',status:'unavailable',text:'不可用'},{name:'变更记录',icon:'history',status:'unknown',text:'未取得'},{name:'知识检索',icon:'book',status:'unknown',text:'未核实'}];
const state = {page:'diagnosis',scene:'stopped',tab:'report',role:'user',running:false,empty:false,platform:'dependencies',kb:'runbooks',runStep:0,timer:null};
let records = ['stopped','config','latency'];
let drawerReturnFocus = null;
let drawerReturnSelector = null;
let toastTimer = null;
const documents = {
  runbooks:[{name:'服务连接失败排查手册.md',status:'已入库',chunks:12,size:18420},{name:'配置变更核对清单.pdf',status:'已入库',chunks:8,size:285400}],
  cases:[{name:'依赖超时故障复盘.docx',status:'已入库',chunks:16,size:42800}]
};
const roleNames = {user:'普通用户',auditor:'审计用户',admin:'管理员'};
const placement = {aiops:'诊断工作空间',knowledge_base:'运维知识库',health:'能力检查 / 平台维护',auth:'账号与权限',monitor:'平台维护',storage:'平台维护',chat:'旧版辅助工具',assistant:'退出主导航',agent:'退出主导航',evaluation:'知识问答辅助工具',loadfile:'历史兼容'};
const scene = () => sceneData[state.scene];

function toast(message) { clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').hidden = false; toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4200); }
function showPage(name, updateHash = true) {
  if (!$('#page-' + name)) return;
  state.page = name;
  $$('.page').forEach(el => { el.hidden = el.id !== 'page-' + name; el.classList.toggle('active', !el.hidden); });
  $$('[data-page]').forEach(el => { el.classList.toggle('active',el.dataset.page === name); if (el.dataset.page === name) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
  $('#breadcrumb-title').textContent = {diagnosis:'故障诊断',history:'最近诊断',knowledge:'运维知识库',platform:'平台维护',interfaces:'接口与设计依据'}[name];
  $('#sidebar').classList.remove('open'); $('#menu-button').setAttribute('aria-expanded','false');
  if (updateHash) history.replaceState(null,'','#' + name);
  if (name === 'history') renderHistory();
  if (name === 'knowledge') renderKnowledge();
  if (name === 'platform') renderPlatform();
  if (name === 'interfaces') renderApis();
}
function showTab(name) {
  state.tab = name;
  $$('[data-tab]').forEach(el => { const active = el.dataset.tab === name; el.setAttribute('aria-selected',String(active)); el.tabIndex = active ? 0 : -1; });
  $$('.tab-pane').forEach(el => { el.hidden = el.id !== 'pane-' + name; });
}
function evidenceLink(index, text = '') {
  return `<button class="evidence-link" data-evidence="${index}">${icon('file')}${escapeHtml(text || `依据 ${String(index + 1).padStart(2,'0')}`)} ${icon('external')}</button>`;
}
function renderSources() {
  $('#source-list').innerHTML = sources.map(row => `<div class="source-row"><span>${icon(row.icon)}${row.name}</span><span class="source-status ${row.status}"><i class="dot ${row.status === 'available' ? 'green' : row.status === 'unavailable' ? 'orange' : 'gray'}"></i>${row.text}</span></div>`).join('');
}
function renderDiagnosis() {
  const data = scene();
  const chainNotes = state.empty ? ['尚未取证','尚未取证','尚未取证'] : state.running ? ['预设场景 · 待核对','预设场景 · 待核对','预设场景 · 待核对'] : ({stopped:['同请求返回 503','依赖连接被拒绝','停止记录与退出证据'],config:['入口异常 · 503','配置字段待核实','未取得充分观察'],latency:['入口异常 · 503','等待响应超时','响应时长待核对'],approval:['预设服务关系','状态信息不完整','预设依赖 · 待核对'],failed:['仅初步观察到 503','未完成采集','未完成采集']})[state.scene];
  $$('.service-chain small').forEach((el,i)=>{el.textContent=chainNotes[i];});
  $('#downstream-node').classList.toggle('fault-node',!state.empty&&!state.running&&state.scene==='stopped');
  $('#run-state').textContent = state.empty ? '准备开始新的诊断' : state.running ? '正在演示排查' : data.state;
  $('#run-id').textContent = state.empty ? '尚未创建' : data.id;
  $('#run-dot').className = 'dot ' + (state.empty ? 'gray' : state.running ? 'blue' : data.tone === 'success' ? 'green' : data.tone === 'danger' ? 'red' : data.tone === 'blue' ? 'blue' : 'orange');
  $('#copy-id').disabled = state.empty;
  $('#run-button').innerHTML = icon(state.running ? 'stop' : 'play') + `<span>${state.running ? '停止演示' : '演示一次诊断'}</span>`;
  $('#query').disabled = state.running; $('#scenario').disabled = state.running;
  $('#terminal-enabled').disabled = state.running;
  $('#tab-process span').textContent = state.empty ? '0' : '4';
  $('#tab-candidates span').textContent = state.empty ? '0' : String(data.candidates.length);
  $('#tab-evidence span').textContent = state.empty ? '0' : String(data.evidence.length);
  if (state.empty) {
    for (const name of ['report','process','candidates','evidence']) $('#pane-' + name).innerHTML = `<div class="empty-row">${icon('pulse')}<h3 style="margin:14px 0 8px">从描述一个具体异常开始</h3><p class="small">说明观察到的现象、涉及服务和已知线索。运行后在这里查看结果与依据。</p></div>`;
    return;
  }
  if (state.running) {
    $('#pane-report').innerHTML = `<div class="running-strip"><span class="spinner"></span><div><strong>正在演示第 ${state.runStep + 1} 步 / 4 步</strong><p class="small">${['整理故障描述并制定检查计划','采集受控范围内的示例证据','对比候选与反对依据','整理结论、引用和待核实项'][state.runStep]}</p><p class="small">预设场景正在本地播放，没有真实 API 请求。</p></div></div>`;
  } else {
    const special = state.scene === 'approval';
    $('#pane-report').innerHTML = `<div class="conclusion-top"><span class="result-label">DIAGNOSIS RESULT</span>${badge(data.label,data.tone)}</div><h2 class="result-title">${escapeHtml(data.title)}</h2><p class="result-description">${escapeHtml(data.description)}</p><div class="result-meta"><span><i class="dot ${data.tone === 'success' ? 'green' : 'orange'}"></i>优先核查 <strong>${escapeHtml(data.target)}</strong></span><span>结论级别 <code>${escapeHtml(data.level)}</code></span></div><div class="section-rule"></div><div class="section-heading"><h3>关键依据</h3><span>现场观察 · 虚构示例</span></div><div class="evidence-findings">${data.findings.map((row,i) => `<div class="finding"><span class="finding-number">${i+1}</span><div class="finding-body"><div class="finding-title">${escapeHtml(row[0])}</div><div class="finding-detail">${escapeHtml(row[1])}</div>${evidenceLink(row[2])}</div></div>`).join('')}</div><div class="section-rule"></div><div class="recommendation"><span>${icon(special?'lock':'arrow')}</span><div><h3>${special?'待审批检查':'下一步建议'}</h3><p>${escapeHtml(data.advice)}</p>${special?'<pre><code>Get-Service -Name localapp</code></pre><button class="text-button" data-action="approval">查看审批流程 '+icon('external')+'</button>':''}</div></div><p class="limit-note">结论限制：${escapeHtml(data.limitation)}</p><div class="report-actions"><button class="text-button" data-action="copy-report">${icon('copy')}复制示例报告</button><button class="text-button" data-action="all-evidence">查看全部 ${data.evidence.length} 条证据 ${icon('arrow')}</button></div>`;
  }
  const steps = [
    ['理解故障，安排有鉴别力的检查','规划角色','区分入口表现、应用侧失败和依赖异常，先取得可核查的现场信息。'],
    ['取得示例现场观察','执行角色',data.findings[0][1]],
    ['根据新证据更新候选','重规划角色',data.candidates.length ? data.candidates[0].unknown : '流程失败，不能完成候选核实。'],
    [state.scene === 'approval' ? '等待终端审批' : state.scene === 'failed' ? '记录错误，保留已取得信息' : '整理结论与仍待核实事项','结论输出',data.limitation]
  ];
  $('#pane-process').innerHTML = `<p class="small muted" style="margin-bottom:22px">预设场景的四阶段展示，不是实际模型轨迹。正式页面优先使用 SSE；历史步快照可能为空。</p>${steps.map((row,i) => `<div class="process-step"><span class="step-icon">${icon(state.running && i >= state.runStep ? 'clock' : 'check')}</span><div class="step-content"><div class="step-title">${escapeHtml(row[0])}<time>阶段 ${i+1}</time></div><p>${escapeHtml(row[2])}</p><span class="step-role">${row[1]} · ${state.running && i >= state.runStep ? '待演示' : '示例记录'}</span></div></div>`).join('')}`;
  $('#pane-candidates').innerHTML = `<p class="small muted" style="margin-bottom:20px">按支持、反对和待核实事项比较，不展示未经校准的概率。</p>${data.candidates.length ? data.candidates.map((item,i) => `<article class="candidate ${i===0?'leading':''}"><div class="candidate-header"><h3>${escapeHtml(item.name)}</h3>${badge(item.status,item.tone)}</div><dl><dt>支持</dt><dd>${escapeHtml(item.support)}</dd><dt>反对</dt><dd>${escapeHtml(item.against)}</dd><dt>待核实</dt><dd>${escapeHtml(item.unknown)}</dd></dl>${evidenceLink(item.ref)}</article>`).join('') : '<div class="empty-row">诊断未完成，没有可呈现的候选判断。</div>'}`;
  $('#pane-evidence').innerHTML = `<div class="section-heading"><h3>本次取证记录</h3><span>${roleNames[state.role]} · ${state.role==='user'?'脱敏信息':'可查看示例原始字段'}</span></div><div class="table-scroll"><table class="evidence-table"><thead><tr><th>信息与来源</th><th>可用状态</th><th>详情</th></tr></thead><tbody>${data.evidence.map((item,i) => `<tr><td><div class="evidence-cell"><strong>${escapeHtml(item.summary)}</strong><code>${escapeHtml(item.service)} · ${escapeHtml(item.kind)}</code></div></td><td>${badge(item.status==='ok'?'已取得':item.status==='partial'?'部分信息':'不可用',item.status==='ok'?'success':'warning')}</td><td>${evidenceLink(i,'打开')}</td></tr>`).join('')}</tbody></table></div><p class="limit-note">正式列表来自 GET /aiops/runs/{thread_id}/evidence。不可用或截断记录不能用于排除未覆盖问题。</p>`;
}
function setScene(name, updateInput = true) {
  if (!sceneData[name]) return;
  stopDemo(false);
  state.scene = name; state.empty = false; state.runStep = 0;
  $('#scenario').value = name;
  if (updateInput) $('#query').value = scene().query;
  $('#terminal-enabled').checked = name === 'approval';
  showTab('report'); renderDiagnosis();
}
function stopDemo(notify = true) {
  clearTimeout(state.timer); state.timer = null;
  const wasRunning = state.running;
  state.running = false;
  if (wasRunning && notify) { state.empty = true; renderDiagnosis(); toast('已停止本地演示。没有真实任务或模型请求。'); }
}
function runDemo() {
  if (state.running) { stopDemo(); return; }
  if (!$('#query').value.trim()) { $('#query').focus(); toast('请先描述故障现象。'); return; }
  state.scene = $('#scenario').value; state.empty = false; state.running = true; state.runStep = 0;
  showTab('report'); renderDiagnosis();
  function tick() {
    if (!state.running) return;
    state.runStep += 1;
    if (state.runStep >= 4) {
      state.running = false;
      if (!records.includes(state.scene)) records.unshift(state.scene);
      $$('.nav-item[data-page="history"] .small-count').forEach(el => { el.textContent = String(records.length); });
      renderDiagnosis(); toast('本地演示结束。所有结论和证据均为虚构示例。');
    } else { renderDiagnosis(); state.timer = setTimeout(tick,850); }
  }
  state.timer = setTimeout(tick,850);
}
function openDrawer(title, html, eyebrow = 'DETAIL') {
  if ($('#drawer').hidden) {
    drawerReturnFocus = document.activeElement;
    drawerReturnSelector = drawerReturnFocus.id ? '#'+CSS.escape(drawerReturnFocus.id) : drawerReturnFocus.dataset.evidence !== undefined ? `#pane-${state.tab} [data-evidence="${drawerReturnFocus.dataset.evidence}"]` : null;
  }
  $('#drawer-title').textContent = title; $('#drawer-eyebrow').textContent = eyebrow; $('#drawer-body').innerHTML = html;
  $('#overlay').hidden = false; $('#drawer').hidden = false; document.body.style.overflow = 'hidden';
  $('.app').inert = true; $('#sidebar').inert = true;
  $('#close-drawer').focus();
}
function closeDrawer() { $('#drawer').hidden = true; $('#overlay').hidden = true; document.body.style.overflow = ''; $('.app').inert = false; $('#sidebar').inert = false; const target = drawerReturnFocus?.isConnected ? drawerReturnFocus : drawerReturnSelector ? $(drawerReturnSelector) : $('#main'); target?.focus(); }
function showEvidence(index) {
  const item = scene().evidence[index]; if (!item) return;
  const permitted = state.role !== 'user';
  openDrawer(item.kind,`${badge('界面演示 · 虚构证据','blue')}<h3>${escapeHtml(item.summary)}</h3><dl><dt>证据 ID</dt><dd><code>${evidenceIds[index]}</code></dd><dt>所属服务</dt><dd>${escapeHtml(item.service)}</dd><dt>来源工具</dt><dd><code>${escapeHtml(item.tool)}</code></dd><dt>采集时间</dt><dd>2026-11-13 10:23:40 +08:00（示例）</dd><dt>可用状态</dt><dd>${escapeHtml(item.status)}</dd><dt>当前角色</dt><dd>${roleNames[state.role]}（演示切换）</dd></dl><h3>信息范围</h3><p>${item.status==='ok'?'仅覆盖本次采集的对象和时刻。':item.status==='partial'?'本条信息不完整，缺失部分仍保留未知。':'本次没有取得该来源的数据，不能判定对象正常。'}</p>${permitted?'<h3>示例原始字段</h3><pre>'+escapeHtml(item.text)+'</pre>':'<div class="notice" style="margin-top:20px">普通用户查看脱敏元数据。原始字段由后端角色权限控制，本页默认不展示。</div><button class="button secondary" data-action="account">查看演示角色与权限</button>'}<p class="small">此内容由原型预设，不是实际 Probe 返回，也不是任何历史实验的证据。</p>`,'EVIDENCE DETAIL');
}
async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
    else { const area = document.createElement('textarea'); area.value = text; document.body.append(area); area.select(); const copied = document.execCommand('copy'); area.remove(); if (!copied) throw new Error('Copy unavailable'); }
    toast('已复制。');
  } catch { openDrawer('可手动复制内容','<pre>'+escapeHtml(text)+'</pre>','COPY'); }
}
function reportText() { const data = scene(); return `[界面演示 / 虚构场景]\n${data.title}\n结论：${data.label}\n${data.description}\n\n依据：\n${data.findings.map((row,i)=>`${i+1}. ${row[0]}：${row[1]}`).join('\n')}\n\n建议：${data.advice}\n限制：${data.limitation}`; }
function renderHistory() {
  const query = $('#history-search').value.trim().toLowerCase(), filter = $('#history-filter').value;
  const items = records.map(key=>({key,...sceneData[key]})).filter(item=>(filter==='all'||item.level===filter) && `${item.title} ${item.id} ${item.query}`.toLowerCase().includes(query));
  $('#history-body').innerHTML = items.length ? items.map(item=>`<tr><td><span class="record-title">${escapeHtml(item.title)}</span><code>${item.id} · 示例本机记录</code></td><td>${badge(item.label,item.tone)}</td><td>${escapeHtml(item.target)}</td><td>${item.date}</td><td><button class="text-button" data-open-scene="${item.key}">查看 ${icon('arrow')}</button></td></tr>`).join('') : '<tr><td colspan="5" class="empty-row">没有匹配的本机示例记录。</td></tr>';
}
function renderKnowledge() {
  const isBm25 = state.kb === 'runbooks';
  $('#kb-title').textContent = isBm25 ? '服务排查手册' : '历史故障案例';
  $('#kb-description').textContent = isBm25 ? '排查步骤与常见错误 · BM25' : '历史事件与处理经验 · 混合检索';
  $$('[data-kb]').forEach(el=>el.classList.toggle('active',el.dataset.kb===state.kb));
  $('#document-body').innerHTML = documents[state.kb].map((doc,i)=>`<tr><td><div class="record-title">${icon('file')} ${escapeHtml(doc.name)}</div><code>${doc.size.toLocaleString()} bytes · 示例 / 本机登记</code></td><td>${badge(doc.status,doc.chunks?'success':'neutral')}</td><td>${doc.chunks || '—'}</td><td><button class="text-button" data-document="${i}">${doc.chunks?'预览与分块':'查看登记'}</button></td></tr>`).join('');
  $('#retrieval-hint').textContent = isBm25 ? '对应 POST /knowledge-bases/{kb_id}/search（仅 BM25）。此处使用固定片段演示。' : '此库为混合检索。当前独立检索接口不支持此模式，不能直接套用 BM25 入口。';
  $('#retrieval-button').disabled = !isBm25; $('#retrieval-query').disabled = !isBm25;
  $('#retrieval-results').hidden = true;
}
function showDocument(index) {
  const doc = documents[state.kb][index]; if (!doc) return;
  openDrawer(doc.name,`${badge(doc.chunks?'示例文档':'仅本机登记','blue')}<h3>文档信息</h3><dl><dt>状态</dt><dd>${escapeHtml(doc.status)}</dd><dt>文件大小</dt><dd>${doc.size.toLocaleString()} bytes</dd><dt>分块数</dt><dd>${doc.chunks || '尚未解析'}</dd><dt>来源</dt><dd>${doc.chunks?'原型内置示例，没有真实原文件':'用户选择的本机文件，仅登记名称和大小'}</dd></dl>${doc.chunks?'<h3>示例片段 · 第 1 块</h3><pre>连接失败应先区分连接被拒绝、建立连接超时以及等待响应超时。\n结合配置、监听与同请求日志检查，不能仅凭入口 503 确认根因。</pre><p>正式文档预览使用 /documents/{doc_id}/preview；分块来自 /documents/{doc_id}/chunks。</p>':'<p>文件内容未读取、未上传、未解析。正式入库需调用知识库上传接口并跟踪处理状态。</p>'}<p>知识经验不能替代当前现场证据。</p>`,'KNOWLEDGE DOCUMENT');
}
function renderPlatform() {
  $$('[data-platform]').forEach(el=>el.classList.toggle('active',el.dataset.platform===state.platform));
  const target = $('#platform-content');
  if (state.platform==='dependencies') {
    const deps=[['主机 Probe','已连接','success','现场进程、端口、日志与配置取证','probe'],['日志检索服务','不可用','warning','查询失败需明确标记；不能视为无异常','mcp_cls'],['监控指标服务','不可用','warning','缺少指标源时使用其余可用证据','mcp_monitor'],['任务队列','可用','success','文档异步处理所需基础设施','rabbitmq'],['缓存','可用','success','平台缓存与会话支撑','redis'],['向量库','可用','success','知识库向量检索依赖','milvus'],['文件存储','可用','success','文档与个人对象存储','minio'],['模型服务','未验证调用','neutral','依赖探活不能替代一次真实模型请求验证','llm']];
    target.innerHTML=`<div class="dependency-grid">${deps.map(d=>`<article class="panel dependency-card"><div class="card-heading"><h3>${d[0]}</h3>${badge(d[1],d[2])}</div><p>${d[3]}</p><code>services.${d[4]} · 示例状态</code></article>`).join('')}</div><div class="panel maintenance-section"><h2>平台健康与诊断能力分开判断</h2><p>GET /health/dependencies 返回平台依赖状态，未覆盖知识、变更所有来源。Probe 字段是否存在受服务器配置影响；没有数据时显示“未核实”。</p></div>`;
  } else if (state.platform==='ingestion') {
    target.innerHTML=`<div class="panel maintenance-section" style="margin-top:0"><div class="card-heading"><h2>Worker 与消息队列</h2>${badge('降级：无在线 Worker','warning')}</div><p>消息中间件可达，但没有在线 Worker；新异步任务可能堆积。以下数字仅为示例。</p><div class="worker-summary"><div><strong>0</strong><span>在线 Worker</span></div><div><strong>—</strong><span>执行中 · 无完整统计</span></div><div><strong>—</strong><span>预取任务 · 无完整统计</span></div></div><code>GET /health/queues → status=degraded</code></div><div class="panel maintenance-section"><h2>文档入库任务</h2><p>这是知识库入库任务，不是 Agent 的诊断任务。删除 monitor 记录实际会删除文档数据库记录，不作为“取消诊断”操作。</p><div class="table-scroll" style="margin-top:17px"><table><thead><tr><th>文档</th><th>状态</th><th>信息</th></tr></thead><tbody><tr><td>配置变更核对清单.pdf</td><td>${badge('已完成','success')}</td><td>示例记录 · 8 个分块</td></tr><tr><td>新排查资料.md</td><td>${badge('待处理','warning')}</td><td>示例记录 · 等待执行</td></tr></tbody></table></div></div>`;
  } else if (state.platform==='files') {
    target.innerHTML=`<div class="panel maintenance-section" style="margin-top:0"><div class="card-heading"><h2>个人文件存储</h2>${badge('用户命名空间隔离','blue')}</div><p>对象存储维护从诊断主界面移出。这里仅展示已存在的后端能力，不进行上传、删除或预签名请求。</p><div class="table-scroll" style="margin-top:18px"><table><thead><tr><th>操作</th><th>后端接口</th></tr></thead><tbody>${[['列出文件','GET /storage/files'],['下载 / 预览','GET /storage/download/{object_name:path} · /storage/preview/{object_name:path}'],['上传文件','POST /storage/upload'],['批量删除','POST /storage/batch-delete'],['预签名链接','GET /storage/url/{object_name:path}']].map(row=>`<tr><td>${row[0]}</td><td><code>${row[1]}</code></td></tr>`).join('')}</tbody></table></div></div>`;
  } else {
    target.innerHTML=accountHtml();
  }
}
function accountHtml() {
  return `<div class="account-grid"><div class="panel"><h2>当前身份</h2><dl><dt>用户</dt><dd>孙同学（演示）</dd><dt>角色</dt><dd>${roleNames[state.role]}</dd><dt>诊断范围</dt><dd>仅自己的诊断；管理员也受所有权限制</dd></dl><div class="role-select"><label>演示角色 <select class="demo-role">${Object.entries(roleNames).map(([key,name])=>`<option value="${key}" ${state.role===key?'selected':''}>${name}</option>`).join('')}</select></label></div><p class="small muted">仅切换本原型的可见内容，不会修改真实账号权限。</p></div><div class="panel"><h2>权限边界</h2><p class="small muted" style="margin:12px 0;line-height:2">普通用户查看脱敏证据；auditor/admin 可取得服务器允许的原始字段。管理员可以列出用户并修改他人角色，不能修改自己的角色。</p><code>GET /auth/me<br>GET /auth/users · admin<br>PATCH /auth/users/{user_id}/role · admin</code><p class="small muted" style="margin-top:16px">正式权限必须由后端判定，本页角色切换不能作为安全边界。</p></div></div>`;
}
function showAccount() { openDrawer('账号与证据权限',accountHtml(),'ACCESS & IDENTITY'); }
function renderApis() {
  const inventory = window.API_INVENTORY;
  if (!inventory) { $('#api-body').innerHTML='<tr><td colspan="5" class="empty-row">接口清单未加载，请将 api-inventory.js 与 HTML 放在同一目录。</td></tr>';return; }
  const query=$('#api-search').value.trim().toLowerCase(), module=$('#api-module').value;
  const items=inventory.routes.filter(row=>(module==='all'||module===row.module)&&`${row.path} ${row.purpose} ${row.function} ${row.methods.join(' ')}`.toLowerCase().includes(query));
  $('#api-count').textContent=`${items.length} / ${inventory.route_count} 个路由`;
  $('#api-body').innerHTML=items.length?items.map(row=>`<tr><td>${row.methods.map(method=>`<span class="method ${method.toLowerCase()}">${method}</span>`).join(' ')}</td><td><code>${escapeHtml(row.path)}</code><small>${escapeHtml(row.purpose)}</small></td><td>${escapeHtml(row.auth)}</td><td>${placement[row.module]}</td><td><button class="text-button" data-api="${window.API_INVENTORY.routes.indexOf(row)}">合同 ${icon('arrow')}</button></td></tr>`).join(''):'<tr><td colspan="5" class="empty-row">没有匹配接口。</td></tr>';
}
function showApi(index) {
  const row=window.API_INVENTORY.routes[index];if(!row)return;
  const schemaNames=new Set(row.parameters.map(p=>p.type));
  const models=window.API_INVENTORY.models.filter(model=>model.module===row.module&&schemaNames.has(model.name));
  openDrawer(row.methods.join(' / ')+' '+row.path,`<p>${escapeHtml(row.purpose)}</p><dl><dt>鉴权</dt><dd>${escapeHtml(row.auth)}</dd><dt>响应模型</dt><dd><code>${escapeHtml(row.response_model||row.return_annotation||'无显式 response_model')}</code></dd><dt>源码</dt><dd><code>${escapeHtml(row.source)}:${row.line}</code></dd><dt>界面归属</dt><dd>${placement[row.module]}</dd></dl><h3>参数与依赖注入</h3><pre>${escapeHtml(row.parameters.map(p=>`${p.name}: ${p.type||'未标注'}${p.default!==null?' = '+p.default:'（必填）'}`).join('\n'))}</pre>${models.map(model=>`<h3>${escapeHtml(model.name)} 模型字段</h3><p class="small">父类：${escapeHtml(model.bases.join(', '))}；继承字段见完整 JSON。</p><pre>${escapeHtml(model.fields.map(f=>`${f.name}: ${f.type}${f.default!==null?' = '+f.default:'（必填）'}`).join('\n'))}</pre>`).join('')}<h3>源码返回表达式</h3><pre>${escapeHtml(row.responses.join('\n\n')||'见函数执行链')}</pre><h3>显式错误分支</h3><pre>${escapeHtml(row.http_errors.join('\n')||'无本函数直接声明的 HTTPException；依赖与服务仍可能失败。')}</pre><p>静态合同，不代表线上验证通过。全量模型、源码指纹和独立 MCP 工具见随附接口文件。</p>`,'API CONTRACT');
}
function showDesign() {
  openDrawer('AIOps 应该是整个工作空间的中心',`<p>以导师版开题的五模块为范围：知识经验辅助诊断；规划、候选管理、取证与结论输出共同构成主页面。</p><h3>这版收缩了什么</h3><ul><li>故障诊断成为默认首页，首屏不再展示知识库数量和平台依赖总绿灯。</li><li>助手搭建、通用 Agents 和聊天退出一级导航。</li><li>监控与队列合并到平台维护，问答评测不冒充诊断实验。</li></ul><h3>后端决定的边界</h3><ul><li>有单次诊断读取，没有诊断列表、取消、任意重试接口。</li><li>只能读取唯一配置的 Probe 目标，没有目标目录 CRUD。</li><li>报告、候选与证据分别呈现；失败和未核实不会包装为成功。</li><li>终端命令依赖外部审批，页面不能代替授权。</li></ul><h3>可继续评审</h3><p>尝试切换场景、结论标签、候选和证据，检查这套界面能否让人迅速说清：查到了什么、为什么这么判断、还缺什么。</p><a class="drawer-link" href="设计说明.md" target="_blank" rel="noopener">打开完整设计说明 ↗</a><a class="drawer-link" href="接口全量清单.md" target="_blank" rel="noopener">打开后端全量接口清单 ↗</a><button class="button secondary" data-action="api-page">浏览 78 个接口 ${icon('arrow')}</button>`,'DESIGN RATIONALE');
}
function showApproval() {
  openDrawer('终端命令审批与续跑',`${badge('本地场景，没有实际审批会话','blue')}<h3>拟检查命令（示例）</h3><pre>Get-Service -Name localapp</pre><p>正式接口会返回 terminal_approval 与 termcp_ui_url。用户在 Termcp 审批后，当前页面调用 /aiops/runs/{thread_id}/continue，由后端重新核验状态与有效期。</p><p>没有审批、审批过期或当前不是终端待审批状态时，不应续跑。本页面没有可替代 Termcp 的“直接批准”按钮。</p><p>受控终端默认配置关闭时，启动请求可能返回 503。</p>`,'HUMAN REVIEW');
}

document.addEventListener('click', event => {
  const nav=event.target.closest('[data-page]');if(nav){showPage(nav.dataset.page);return;}
  const tab=event.target.closest('[data-tab]');if(tab){showTab(tab.dataset.tab);return;}
  const ref=event.target.closest('[data-evidence]');if(ref){showEvidence(Number(ref.dataset.evidence));return;}
  const record=event.target.closest('[data-open-scene]');if(record){setScene(record.dataset.openScene);showPage('diagnosis');return;}
  const kb=event.target.closest('[data-kb]');if(kb){state.kb=kb.dataset.kb;renderKnowledge();return;}
  const doc=event.target.closest('[data-document]');if(doc){showDocument(Number(doc.dataset.document));return;}
  const maintenance=event.target.closest('[data-platform]');if(maintenance){state.platform=maintenance.dataset.platform;renderPlatform();return;}
  const api=event.target.closest('[data-api]');if(api){showApi(Number(api.dataset.api));return;}
  const action=event.target.closest('[data-action]')?.dataset.action;
  if(action==='copy-report')copyText(reportText());
  if(action==='all-evidence')showTab('evidence');
  if(action==='approval')showApproval();
  if(action==='account')showAccount();
  if(action==='api-page'){closeDrawer();showPage('interfaces');}
});
$('#run-button').addEventListener('click',runDemo);
$('#scenario').addEventListener('change',()=>setScene($('#scenario').value));
$('#new-diagnosis').addEventListener('click',()=>{stopDemo(false);state.empty=true;$('#query').value='';renderDiagnosis();showTab('report');$('#query').focus();});
$('#query').addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();runDemo();}});
$('#copy-id').addEventListener('click',()=>copyText(scene().id));
$('#advanced-toggle').addEventListener('click',()=>{const hidden=!$('#advanced-options').hidden;$('#advanced-options').hidden=hidden;$('#advanced-toggle').setAttribute('aria-expanded',String(!hidden));});
$('#terminal-enabled').addEventListener('change',()=>{toast('此开关仅演示 terminal_enabled；场景结果由演示场景选项决定。');});
$('#open-evidence').addEventListener('click',()=>showTab('evidence'));
$('#menu-button').addEventListener('click',()=>{const open=$('#sidebar').classList.toggle('open');$('#menu-button').setAttribute('aria-expanded',String(open));});
$('#design-button').addEventListener('click',showDesign);
$('#account-button').addEventListener('click',showAccount);
$('#close-drawer').addEventListener('click',closeDrawer);
$('#overlay').addEventListener('click',closeDrawer);
$('#history-search').addEventListener('input',renderHistory);$('#history-filter').addEventListener('change',renderHistory);
$('#restore-form').addEventListener('submit',event=>{event.preventDefault();const id=$('#restore-id').value.trim();const match=Object.keys(sceneData).find(key=>sceneData[key].id===id);if(!match){toast('本地没有这个示例 ID。正式接入需向后端读取并核验所有权。');return;}setScene(match);showPage('diagnosis');toast('已打开示例诊断。没有请求真实后端。');});
$('#upload-document').addEventListener('click',()=>$('#document-file').click());
$('#document-file').addEventListener('change',()=>{const file=$('#document-file').files[0];if(!file)return;documents[state.kb].push({name:file.name,status:'仅本机登记',chunks:0,size:file.size});renderKnowledge();toast('仅登记文件名称和大小，没有上传或解析。');$('#document-file').value='';});
$('#new-kb').addEventListener('click',()=>{
  const route=window.API_INVENTORY.routes.findIndex(row=>row.module==='knowledge_base'&&row.function==='create_knowledge_base');showApi(route);
});
$('#retrieval-form').addEventListener('submit',event=>{event.preventDefault();if(state.kb!=='runbooks')return;const query=$('#retrieval-query').value.trim();if(!query)return;$('#retrieval-results').hidden=false;$('#retrieval-results').innerHTML=`<div class="retrieval-hit"><strong>固定示例片段 · 非真实检索结果</strong>输入关键词：${escapeHtml(query)}<br>连接拒绝、建立连接超时与等待响应超时需分别核查。对照目标配置、端口监听和同请求日志，逐步区分候选原因。<br><small>来源：服务连接失败排查手册.md · 第 1 块（示例）</small></div>`;});
document.addEventListener('change',event=>{if(event.target.matches('.demo-role')){state.role=event.target.value;$('#profile-role').textContent=roleNames[state.role];renderDiagnosis();if(state.page==='platform')renderPlatform();if(!$('#drawer').hidden)showAccount();toast('已切换演示角色；真实授权仍由后端控制。');}});
$('#api-search').addEventListener('input',renderApis);$('#api-module').addEventListener('change',renderApis);
$('#download-inventory').addEventListener('click',()=>{const blob=new Blob([JSON.stringify(window.API_INVENTORY,null,2)],{type:'application/json;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='aiops-api-inventory-20261113.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);toast('已导出静态源码接口清单。');});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'){if(!$('#drawer').hidden)closeDrawer();$('#sidebar').classList.remove('open');$('#menu-button').setAttribute('aria-expanded','false');}
  if(!$('#drawer').hidden&&event.key==='Tab'){
    const focusable=$$('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',$('#drawer')).filter(el=>!el.hidden&&el.getClientRects().length);
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  if(event.target.closest('[role="tablist"]')&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){
    event.preventDefault();const tabs=$$('[data-tab]');let index=tabs.indexOf(document.activeElement);index=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;showTab(tabs[index].dataset.tab);tabs[index].focus();
  }
});
window.addEventListener('hashchange',()=>showPage(location.hash.slice(1)||'diagnosis',false));
hydrateIcons();renderSources();renderDiagnosis();
if(window.API_INVENTORY){$('#api-module').insertAdjacentHTML('beforeend',Object.keys(window.API_INVENTORY.counts).map(name=>`<option value="${name}">${name} (${window.API_INVENTORY.counts[name]})</option>`).join(''));}
showPage(location.hash.slice(1)||'diagnosis',false);
