import {test} from 'node:test';
import assert from 'node:assert/strict';
import scene from '../src/data/scene.json' with {type:'json'};
import {projectScene,timeUTC} from '../src/model.mjs';
test('保存场景保留真实终态与未决原因',()=>{
  assert.equal(scene.kind,'localized_fault');
  assert.equal(scene.evidence.length,10);
  assert.equal(scene.candidates.length,7);
  assert.equal(scene.candidates.find(c=>c.code==='H6').status,'unresolved');
  assert.equal(scene.candidates.find(c=>c.code==='H6').relation,'neutral');
  assert.equal(scene.candidates.filter(c=>c.status==='supported').length,2);
  assert.equal(scene.candidates.filter(c=>c.status==='excluded').length,1);
});
test('不完整摘要保持不完整，不提升原文权限',()=>{
  const projected=projectScene({status:'completed',diagnosis:{kind:'localized_fault',alternatives:[],observed_findings:[]},investigation:{candidates:[],candidate_check_progress:{},leading_id:null,check_progress:[]}},
    {can_read_raw:false,evidence:[{evidence_id:'e1',kind:'ports',summary:'{"ports":[',collected_at:'2026-11-14T09:07:50+08:00'}]});
  assert.equal(projected.evidence[0].complete,false);
  assert.equal(projected.rawAvailable,false);
  assert.equal(projected.evidence[0].title,'主机端口摘要不完整');
  assert.equal(timeUTC('2026-11-14T09:07:50+08:00'),'01:07:50');
});
test('未决关系不因候选排序或证据关联而变成支持',()=>{
  const projected=projectScene({status:'completed',diagnosis:{kind:'localized_fault',alternatives:[{hypothesis_id:'h1',status:'unresolved',evidence:[{evidence_id:'e1'}]}],observed_findings:[]},investigation:{candidates:[{id:'h1',status:'supported',relation:'neutral',evidence_ids:[],explanation:'可能原因'}],candidate_check_progress:{h1:[{evidence_ids:['e1']}]},leading_id:'h1',check_progress:[]}},
    {can_read_raw:false,evidence:[{evidence_id:'e1',kind:'processes',summary:JSON.stringify({service:'downstream',matched_count:0,inspected_count:1,skipped_count:0,processes:[]}),collected_at:'2026-11-14T09:07:50+08:00'}]});
  assert.equal(projected.candidates[0].status,'unresolved');
  assert.equal(projected.candidates[0].relation,'neutral');
  assert.deepEqual(projected.candidates[0].related,['e1']);
  for(const candidate of scene.candidates) for(const id of candidate.related) assert.ok(scene.evidence.some(e=>e.id===id));
  const text=JSON.stringify(scene);
  assert.ok(!text.includes('DESKTOP-'));
  assert.ok(!text.includes('D:\\\\'));
  assert.ok(!text.includes('downstream.stop'));
});
