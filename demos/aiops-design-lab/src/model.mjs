const titles = {
  'h-b541e2fe50bb140e': 'downstream 进程未被发现',
  'h-f89df200db7afe92': '端口 4634 未监听',
  'h-bf0945377e1d94de': '到 localapp 的 TCP 链路故障',
  'h-7c2669bb76d10b52': 'localapp 下游端点配置错配',
  'h-a0fc99d99b13a394': '连接建立后的内部处理错误',
  'h-3b7779d994e780c7': 'downstream 从未成功启动',
  'h-c4075d90bed5014a': 'downstream 停止引发请求失败',
};
const notes = {
  'h-b541e2fe50bb140e': '本次进程快照没有匹配项，退出原因仍需结合日志判断。',
  'h-f89df200db7afe92': '端口快照未发现监听记录，尚不能说明服务为何退出。',
  'h-bf0945377e1d94de': '本次 TCP 探测成功，localapp 返回 HTTP 503。',
  'h-7c2669bb76d10b52': '配置端口为 4634，加载哈希与快照一致；最终记录仍保留未决状态。',
  'h-a0fc99d99b13a394': '该请求在连接建立前超时，尚无连接建立后出错的证据。',
  'h-3b7779d994e780c7': '日志已记录实例启动与退出，最终记录仍保留未决状态。',
  'h-c4075d90bed5014a': '日志记录了停止与退出，但停止发起者及完整异常传播关系尚未确认。',
};
export const timeUTC = at => new Date(at).toISOString().slice(11, 19);
const kindLabels = {inventory:'环境清单', processes:'进程快照', ports:'端口快照', text_logs:'应用日志', configuration:'配置快照', dependency_probe:'依赖探测'};
const eventLabels = {service_started:'服务启动', shutdown_requested:'收到停止请求', service_exited:'完成退出', request_completed:'业务请求结束'};

export function projectScene(run, source) {
  const evidence = source.evidence.map((record, index) => {
    let data;
    try { data = JSON.parse(record.summary); } catch { data = null; }
    const subject = data?.service || data?.dependency || (data?.local_port ? `端口 ${data.local_port}` : record.kind === 'inventory' ? '受控测试环境' : '主机端口');
    let title = '', fields = [], events = [], excerpt = {};
    if (!data) {
      title = '主机端口摘要不完整';
      fields = [['保存状态','摘要已截断'],['可用操作','查看后续的 4634 定向端口快照']];
      excerpt = {note:'保存摘要被截断，未作为完整端口快照展示'};
    } else if (record.kind === 'inventory') {
      title = '已登记 3 个业务服务';
      fields = [['系统',data.system],['版本',data.release],['Probe',data.probe_version],['服务',Object.keys(data.configured_services).join(' / ')]];
      excerpt = {system:data.system,release:data.release,probe_version:data.probe_version,services:Object.keys(data.configured_services)};
    } else if (record.kind === 'processes') {
      title = data.matched_count ? `${data.matched_count} 条匹配进程` : '未发现匹配进程';
      fields = [['匹配进程',String(data.matched_count)],['已枚举进程',String(data.inspected_count)],['跳过',String(data.skipped_count)]];
      excerpt = {service:data.service,matched_count:data.matched_count,inspected_count:data.inspected_count,processes:data.processes.map(p=>({pid:p.pid,name:p.name}))};
    } else if (record.kind === 'ports') {
      title = data.ports.length ? `${data.ports.length} 条监听记录` : `端口 ${data.local_port} 无监听`;
      fields = [['目标端口',String(data.local_port)],['监听记录',String(data.matched_count)],['采集方式','定向端口快照']];
      excerpt = {local_port:data.local_port,ports:data.ports,matched_count:data.matched_count};
    } else if (record.kind === 'configuration') {
      title = '下游端口 4634 · 超时 0.5 秒';
      fields = [['下游端口',String(data.values.downstream_port)],['连接超时',`${data.values.upstream_timeout_seconds} 秒`],['加载校对','与应用日志中的配置哈希一致']];
      excerpt = {service:data.service,values:data.values,source_sha256:data.source_sha256};
    } else if (record.kind === 'dependency_probe') {
      title = `TCP ${data.tcp === 'ok' ? '可达' : '失败'} · HTTP ${data.http?.status}`;
      fields = [['TCP',data.tcp === 'ok' ? '连接成功' : '连接失败'],['HTTP',String(data.http?.status)],['耗时',`${data.elapsed_ms} ms`],['响应',data.http?.body_prefix]];
      excerpt = {dependency:data.dependency,port:data.port,tcp:data.tcp,http:data.http,elapsed_ms:data.elapsed_ms};
    } else if (record.kind === 'text_logs') {
      const lines = data.lines.map(line=>JSON.parse(line));
      title = data.service === 'downstream' ? '启动后收到停止请求，随后退出' : '连接阶段超时，业务请求返回 503';
      events = lines.map(line=>({at:line.at,time:timeUTC(line.at)+'.'+new Date(line.at).toISOString().slice(20,23),label:eventLabels[line.event]||line.event,code:line.event,detail:line.event==='service_started'?`PID ${line.pid} · 监听 ${line.listen_port}`:line.event==='shutdown_requested'?'受控停止 · 发起者未知':line.event==='service_exited'?'停止流程完成':`HTTP ${line.status} · ${line.duration_ms} ms · 连接未建立`}));
      fields = [['返回日志',`${lines.length} 条`],['记录对象',data.service],['日志窗口',`${events[0].time} — ${events.at(-1).time} UTC`]];
      excerpt = {service:data.service,lines:lines.map(line=>({at:line.at,pid:line.pid,event:line.event,...(line.listen_port?{listen_port:line.listen_port}:{}),...(line.reason?{reason:line.reason}:{}),...(line.stop_request?{stop_request:{channel:line.stop_request.channel,initiator:line.stop_request.initiator}}:{}),...(line.status?{path:line.path,status:line.status,duration_ms:line.duration_ms,upstream:line.upstream,upstream_request:line.upstream_request,error_type:line.error_type}:{}),...(line.configuration?{configuration:{loading:line.configuration.loading,source_sha256:line.configuration.source_sha256}}:{})}))};
    }
    return {id:record.evidence_id,index,code:`E${String(index+1).padStart(2,'0')}`,kind:record.kind,kindLabel:kindLabels[record.kind],subject,title,time:timeUTC(record.collected_at),at:record.collected_at,fields,events,excerpt,complete:!!data};
  });
  const candidates = run.investigation.candidates.map((item,index)=>{
    const final = run.diagnosis.alternatives.find(a=>a.hypothesis_id===item.id);
    const progress = run.investigation.candidate_check_progress[item.id] || [];
    const status = final?.status || (item.status==='excluded'?'excluded':'unresolved');
    const direct = item.evidence_ids || [];
    const related = [...new Set([...direct,...(final?.evidence||[]).map(e=>e.evidence_id),...progress.flatMap(p=>p.evidence_ids)])].filter(id=>evidence.some(e=>e.id===id));
    return {id:item.id,code:`H${index+1}`,title:titles[item.id] || item.explanation,status,statusLabel:({supported:'现场支持',excluded:'已排除',unresolved:'待验证'})[status],type:item.condition?'现场条件':'原因解释',relation:item.relation,direct,related,note:notes[item.id] || final?.limitation || '',question:progress[0]?.question || '',explanation:item.explanation};
  });
  const findings = [...new Map(run.diagnosis.observed_findings.map(f=>[f.evidence_id,{code:f.code,id:f.evidence_id}])).values()];
  return {date:source.evidence[0].collected_at.slice(0,10),kind:run.diagnosis.kind,status:run.status,leadingId:run.investigation.leading_id,candidates,evidence,findings,checks:run.investigation.check_progress.map(p=>({question:p.question,evidenceIds:p.evidence_ids,status:p.status})),rawAvailable:source.can_read_raw};
}
