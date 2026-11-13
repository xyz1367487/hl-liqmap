const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('./load-core.cjs');
test('real navigator keyboard handlers use the visible span even when a distant bucket stretches the overview',()=>{
  const fs=require('node:fs'),vm=require('node:vm');
  const nodes={};
  const node=id=>nodes[id]??=( {hidden:false,addEventListener(){},setAttribute(){},focus(){},matches(){return false;}} );
  const context=vm.createContext({LiqChart:C,$:node,clearTimeout,setTimeout,
    window:{addEventListener(){}},document:{addEventListener(){},querySelectorAll(){return [];}},
    ResizeObserver:class{observe(){}}});
  vm.runInContext(fs.readFileSync(__dirname+'/../chart-ui.js','utf8'),context);
  vm.runInContext('chartContext={domain:[0,51317294.7]};chartWindow=[64000,75000];drawChart=()=>{};wireChart();',context);
  const key=(id,value,shiftKey=false)=>nodes[id].onkeydown({key:value,shiftKey,preventDefault(){}});
  const range=()=>JSON.parse(vm.runInContext('JSON.stringify(chartWindow)',context));
  key('navLow','ArrowRight');
  assert.deepEqual(range(),[64110,75000]);
  vm.runInContext('chartWindow=[64000,75000]',context);
  key('navHigh','ArrowLeft',true);
  assert.deepEqual(range(),[64000,73900]);
  vm.runInContext('chartWindow=[64000,75000]',context);
  key('navSelection','ArrowRight');
  assert.deepEqual(range(),[64110,75110]);
  key('navSelection','Home');
  assert.deepEqual(range(),[0,11000]);
});
const rows=C.normalize({bucket_step:.05,buckets:[
  {side:'L',index:1800,notional:100,positions:1,px_low:90.01,px_high:90.02,lev:[100,0,0,0]},
  {side:'S',index:1800,notional:200,positions:1,px_low:90.03,px_high:90.04,lev:[0,200,0,0]},
  {side:'S',index:200000000,notional:500,positions:1,px_low:10000000.01,px_high:10000000.02,lev:[0,0,500,0]}
]},3);
test('5/10/25/50bp exact hit returns both sides and never attracts a remote occupied cell',()=>{
  for(const factor of [1,2,5,10]){
    const bars=C.coarsen(rows,.05,factor);
    const hit=C.hitPrice(bars,90.025,.05,factor);
    assert.deepEqual(hit.rows.map(b=>b.side),['L','S']);
    assert.deepEqual(hit.rows.map(b=>b.notional),[100,200]);
    assert.equal(C.hitPrice(bars,99,.05,factor).rows.length,0);
    assert.ok(Math.abs(hit.interval[1]-hit.interval[0]-.05*factor)<1e-10);
    assert.equal(C.hitPrice(bars,hit.interval[1],.05,factor).rows.length,0);
    assert.equal(bars.reduce((s,b)=>s+b.notional,0),800);
  }
});
test('schema1 uses original overlapping intervals and does not fabricate a grid',()=>{
  const old=[{side:'L',lo:80,hi:95,notional:100},{side:'S',lo:90,hi:110,notional:300}];
  assert.deepEqual(C.hitPrice(old,92,.05,10,true),{rows:old,interval:null});
  assert.deepEqual(C.hitPrice(old,79,.05,10,true),{rows:[],interval:null});
});
test('navigator preserves zero, extreme prices and current window; panning preserves span',()=>{
  const domain=C.overviewDomain(rows,100,[0,120]);
  assert.deepEqual(domain,[0,10000000.05]);
  assert.deepEqual(C.moveRange([10,30],-100,domain),[0,20]);
  assert.deepEqual(C.moveRange([10,30],1e9,domain),[10000000.05-20,10000000.05]);
  assert.deepEqual(C.overviewDomain(rows,100,[0,20000000]),[0,20000000]);
});
test('regridding/hit/navigation retain hand-calculated original total and cumulative steps',()=>{
  const before=C.cumulative(rows,100);
  assert.deepEqual(before.totals,{L:100,S:500});
  assert.deepEqual(before.past,{L:0,S:200});
  for(const factor of [1,2,5,10]){
    C.hitPrice(C.coarsen(rows,.05,factor),99,.05,factor);
    C.moveRange([80,120],10);
    const after=C.cumulative(rows,100);
    assert.deepEqual(after.points,before.points);
    assert.equal(after.at('L',90.01),100);
    assert.equal(after.at('L',90.02),0);
    assert.equal(after.at('S',10000000.02),500);
  }
});
