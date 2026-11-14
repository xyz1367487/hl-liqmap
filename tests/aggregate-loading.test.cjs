const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const core=require('./load-core.cjs');
const html=fs.readFileSync(__dirname+'/../index.html','utf8');
const block=html.slice(html.indexOf('const AGGREGATE_URL='),html.indexOf("$('ls').oninput"));
const sample=()=>({schema_version:2,generated_at_unix:100,privacy:{scope:'aggregate_only',buckets:'all_nonempty'},coin_list:{updated:'2026-11-11',caliber:'avg_7d',threshold:5000000,coins:[{n:'BTC',v:6000000}]},markets:{BTC:{reference_mark:100,bucket_step:.05,buckets:[]}}});
function harness(fetch){
  const nodes={},storage=new Map(),calls=[];
  const ctx=vm.createContext({LiqChart:core,AbortController,setTimeout,clearTimeout,Date,console,
    aggregateSnapshot:null,netFetching:false,cur:null,coins:[],
    $:id=>nodes[id]??=( {textContent:'',value:'BTC',disabled:false}),
    localStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)||null},
    clearErr(){},drawChart(){},installCoins(next){ctx.coins=next;},cachedCoins(){return [];},renderContext(){},async refresh(){},fetch:async(url,opts)=>{calls.push({url,opts});return fetch(calls.length,url,opts);}});
  vm.runInContext(block,ctx);
  return {ctx,nodes,storage,calls,run:code=>vm.runInContext(code,ctx)};
}
const response=(data=sample())=>({ok:true,text:async()=>JSON.stringify(data)});
test('Raw succeeds without requesting fallbacks; no credentials or redirects',async()=>{
  const h=harness(()=>response());await h.run('loadNet()');assert.equal(h.calls.length,1);
  assert.match(h.calls[0].url,/^https:\/\/raw.githubusercontent.com\//);
  assert.equal(h.calls[0].opts.credentials,'omit');assert.equal(h.calls[0].opts.redirect,'error');
  assert.match(h.nodes.netMeta.textContent,/GitHub Raw/);assert.match(h.nodes.netMeta.textContent,/聚合生成于/);
});
test('Raw network failure falls back to public API with raw Accept',async()=>{
  const h=harness(n=>{if(n===1)throw Error('secret stack/body');return response();});
  await h.run('loadNet()');assert.equal(h.calls.length,2);assert.equal(h.calls[1].opts.headers.Accept,'application/vnd.github.raw+json');
  assert.match(h.nodes.netProg.textContent,/GitHub Raw：网络/);assert.match(h.nodes.netMeta.textContent,/GitHub API/);
});
test('Raw and API failures fall back to CDN',async()=>{
  const h=harness(n=>n<3?{ok:false,status:503}:response());await h.run('loadNet()');
  assert.equal(h.calls.length,3);assert.match(h.calls[2].url,/^https:\/\/cdn.jsdelivr.net\/gh\//);assert.match(h.nodes.netMeta.textContent,/jsDelivr CDN/);
});
test('All sources fail; no snapshot is not valid empty BTC; retry recovers',async()=>{
  let fail=true;const h=harness(()=>{if(fail)throw Error('private body');return response();});
  assert.equal(h.run('aggregateEmptyText()'),'聚合快照尚未加载');
  await h.run('loadNet()');assert.equal(h.ctx.aggregateSnapshot,null);
  assert.match(h.run('aggregateEmptyText()'),/读取失败/);assert.equal(h.nodes.netBtn.disabled,false);
  assert.equal((h.nodes.netProg.textContent.match(/：网络/g)||[]).length,3);assert.doesNotMatch(h.nodes.netProg.textContent,/private|stack/);
  fail=false;await h.run('loadNet()');assert.equal(h.run('aggregateEmptyText()'),'该币暂无真实聚合桶');
  delete h.ctx.aggregateSnapshot.markets.BTC;assert.equal(h.run('aggregateEmptyText()'),'该币暂无真实聚合桶');
});
test('Timeout includes complete response body and aborts; loading state is explicit',async()=>{
  let signal;const h=harness((n,u,o)=>{signal=o.signal;return {ok:true,text:()=>new Promise(()=>{})};});
  await assert.rejects(h.run('readAggregateSource(AGGREGATE_SOURCES[0],10)'),e=>e.category==='超时');assert.equal(signal.aborted,true);
  h.run("aggregateState='loading'");assert.match(h.run('aggregateEmptyText()'),/正在加载/);
});
test('Timeout also bounds connection stage',async()=>{
  const h=harness(()=>new Promise(()=>{}));await assert.rejects(h.run('readAggregateSource(AGGREGATE_SOURCES[0],10)'),e=>e.category==='超时');
});
test('Classifies HTTP, JSON parse, schema and unexpected redirect without body leaks',async()=>{
  for(const [res,category] of [[{ok:false,status:429},'HTTP 429'],[{ok:true,text:async()=>'<secret>'},'解析'],[response({accounts:[]}), 'schema'],[{ok:true,url:'https://unknown.example/private'},'重定向']]){
    const h=harness(()=>res);await assert.rejects(h.run('readAggregateSource(AGGREGATE_SOURCES[0])'),e=>e.category===category&&e.message===category);
  }
});
test('Older fallbacks never replace newer memory or persisted cache; failures preserve chart data',async()=>{
  const h=harness(()=>response());const newer=sample();newer.generated_at_unix=200;h.ctx.aggregateSnapshot=newer;
  const original=JSON.stringify(newer);h.storage.set('liqmap_aggregate_v1',original);
  await h.run('loadNet()');assert.equal(h.ctx.aggregateSnapshot,newer);assert.equal(h.storage.get('liqmap_aggregate_v1'),original);
  assert.equal(h.calls.length,3);assert.equal((h.nodes.netProg.textContent.match(/拒绝倒退/g)||[]).length,3);
  const f=harness(()=>{throw Error();});f.ctx.aggregateSnapshot=newer;await f.run('loadNet()');assert.equal(f.ctx.aggregateSnapshot,newer);
});
test('Startup retains strictly valid cache older than six hours without clearing storage',()=>{
  const h=harness(()=>response());h.storage.set('liqmap_aggregate_v1',JSON.stringify(sample()));
  const start=html.indexOf('    const cached=validateAggregate');const end=html.indexOf('\n  }catch(e){}\n  installCoins',start);
  h.run(html.slice(start,end));assert.equal(h.ctx.aggregateSnapshot.generated_at_unix,100);assert.match(h.nodes.netMeta.textContent,/超过2小时/);
});
test('Watchlist uses its independent empty state and chart algorithms remain untouched',()=>{
  const ui=fs.readFileSync(__dirname+'/../chart-ui.js','utf8');
  assert.ok(ui.includes("watch?'Watchlist 尚无该币有效强平价，请先拉取仓位':aggregateEmptyText()"));
});
