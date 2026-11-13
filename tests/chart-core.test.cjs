// Synthetic prices and amounts only. No real accounts or snapshots.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('./load-core.cjs');
const b=(side,lo,hi,n)=>({side,px_low:lo,px_high:hi,notional:n,positions:1,lo,hi});
const rows=[b('L',90,91,10),b('L',95,96,20),b('L',100,100,3),b('L',100,100,7),b('S',100,100,11),b('S',105,106,30),b('S',110,111,40),b('L',99,101,13),b('S',99,101,17),b('L',102,103,19),b('S',97,98,23)];
test('分界、同价和方向：手算金额及阶跃，不在桶内部插值',()=>{
  const c=C.cumulative(rows,100);
  assert.deepEqual(c.totals,{L:40,S:81});assert.deepEqual(c.uncertain,{L:13,S:17});assert.deepEqual(c.past,{L:19,S:23});
  assert.equal(c.at('L',100),10);assert.equal(c.at('S',100),11);
  assert.equal(c.at('L',95.5),10);assert.equal(c.at('L',95),30);assert.equal(c.at('L',90),40);
  assert.equal(c.at('S',105.5),11);assert.equal(c.at('S',106),41);assert.equal(c.at('S',111),81);
  assert.deepEqual(c.points.L.filter(p=>p.px===100).map(p=>p.value),[0,0,10]);
});
test('金额守恒：累计、跨价待定位与已越过方向之和等于全部原桶',()=>{
  const c=C.cumulative(rows,100);
  for(const side of ['L','S'])assert.equal(c.totals[side]+c.uncertain[side]+c.past[side],rows.filter(b=>b.side===side).reduce((s,b)=>s+b.notional,0));
});
test('跨参考价后按行情价判断；固定桶不重分、不按仓位方向猜价格',()=>{
  const original=JSON.stringify(rows),c=C.cumulative(rows,104);
  assert.equal(c.totals.L,72);assert.equal(c.totals.S,70);assert.equal(c.past.S,51);
  assert.equal(c.at('L',99),42);assert.equal(JSON.stringify(rows),original);
});
test('视窗切换不重置累计，窗外近端金额仍计入，坐标是线性美元',()=>{
  const c=C.cumulative(rows,100);
  assert.equal(c.at('L',90),40); // A [89,92] window still includes 95 and 100 contributions.
  assert.equal(c.at('S',111),81);
  const y=C.linear([0,1000],[400,0]);assert.equal(y(500),200);assert.equal(y(250),300);
  const x=C.linear([80,120],[0,1000]);assert.equal(x(100),500);
  assert.throws(()=>C.linear([1,1],[0,100]));
});
test('小数网格恰好边界、相邻值与科学记数法',()=>{
  assert.equal(C.gridIndex(100.05,.05),2001);assert.equal(C.gridIndex(100.04999999999998,.05),2000);
  assert.equal(C.gridIndex(100.05000000000001,.05),2001);
  assert.equal(C.gridIndex(3e-8,1e-8),3);
});
test('分辨率仅合并桶；名义和仓位数量守恒，旧14档从不拆分',()=>{
  const base=C.localBuckets([{side:'L',liqPx:99.95,n:10},{side:'L',liqPx:100,n:20},{side:'S',liqPx:100,n:30}],100);
  assert.equal(base.length,3);
  for(const factor of [1,2,5,10]){
    const merged=C.coarsen(base,.05,factor);
    assert.equal(merged.reduce((s,b)=>s+b.notional,0),60);assert.equal(merged.reduce((s,b)=>s+b.positions,0),3);
  }
  const legacy=C.normalize({buckets:[{side:'L',band:13,px_low:1,px_high:200,notional:123,positions:4}]},1);
  assert.deepEqual(C.coarsen(legacy,.05,10),legacy);assert.equal(C.cumulative(legacy,100).uncertain.L,123);
});
test('空桶、空市场和相同价格两方向',()=>{
  assert.deepEqual(C.cumulative([],100).totals,{L:0,S:0});
  assert.deepEqual(C.cumulative([b('L',100,100,5),b('S',100,100,6)],100).totals,{L:5,S:6});
});
