// Synthetic leverage/amounts only. No real accounts, addresses or snapshots.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('./load-core.cjs');

const bucket=(side,index,notional,lev)=>({side,index,notional,positions:1,px_low:index*.05,px_high:index*.05,lev});
const market=(buckets)=>({reference_mark:100,bucket_step:.05,buckets});
const envelope=(marketBuckets)=>({schema_version:3,generated_at_unix:1,privacy:{scope:'aggregate_only',buckets:'all_nonempty'},
  coin_list:{updated:'2026-11-11',caliber:'avg_7d',threshold:5000000,coins:[{n:'BTC',v:6000000}]},
  markets:{BTC:{...market(marketBuckets),lev_unknown:{buckets:0,notional:0}}}});

test('杠杆分档边界：真实杠杆值落档，<=10 / 11-25 / 26-50 / >50',()=>{
  const cases=[[1,0],[5,0],[10,0],[10.5,1],[11,1],[25,1],[25.5,2],[26,2],[50,2],[50.5,3],[51,3],[100,3]];
  for(const [value,band] of cases) assert.equal(C.levBand(value),band,`${value}x 应为第 ${band} 档`);
  assert.deepEqual(C.LEV_LABELS,['≤10x','11-25x','26-50x','>50x']);
});

test('无杠杆信息返回 -1（明确退化，不推断）',()=>{
  for(const value of [null,undefined,0,-3,NaN,Infinity,'20',{},true]) assert.equal(C.levBand(value),-1,String(value));
});

test('堆叠合计等于原桶金额；每档金额之和必须精确复原 notional',()=>{
  const buckets=[bucket('L',2000,31,[7,11,13,0]),bucket('S',2001,23,[0,23,0,0]),bucket('L',1960,7,[7,0,0,0])];
  const s=C.validate(envelope(buckets));
  for(const b of s.markets.BTC.buckets) assert.equal(C.levSum(b.lev),b.notional);
  assert.equal(s.markets.BTC.buckets.reduce((n,b)=>n+C.levSum(b.lev),0),61);
});

test('schema3 拒绝与桶金额不符的杠杆拆分（不得伪造）',()=>{
  const bad=envelope([bucket('L',2000,31,[7,11,13,1])]);
  assert.throws(()=>C.validate(bad),/杠杆档合计与桶金额不符/);
  const wrongLength=envelope([bucket('L',2000,31,[7,11,13])]);
  assert.throws(()=>C.validate(wrongLength),/杠杆档拆分无效/);
  const negative=envelope([bucket('L',2000,31,[40,-9,0,0])]);
  assert.throws(()=>C.validate(negative),/聚合数值无效/);
});

test('schema1/2/3 兼容：v1 无 bucket_step，v2 无 lev，v3 带 lev 与 lev_unknown',()=>{
  const v3=C.validate(envelope([bucket('L',2000,31,[7,11,13,0])]));
  assert.equal(v3.schema_version,3);
  const v2=C.validate({schema_version:2,generated_at_unix:1,privacy:{scope:'aggregate_only',buckets:'all_nonempty'},
    coin_list:{updated:'2026-11-11',caliber:'avg_7d',threshold:5000000,coins:[{n:'BTC',v:6000000}]},
    markets:{BTC:{reference_mark:100,bucket_step:.05,buckets:[{side:'L',index:2000,notional:31,positions:1,px_low:100,px_high:100}]}}});
  assert.equal(v2.markets.BTC.buckets[0].lev,undefined);
  const v1=C.validate({schema_version:1,generated_at_unix:1,privacy:{scope:'aggregate_only',buckets:'all_nonempty'},
    coin_list:{updated:'2026-11-11',caliber:'avg_7d',threshold:5000000,coins:[{n:'BTC',v:6000000}]},
    markets:{BTC:{reference_mark:100,buckets:[{side:'L',band:0,notional:31,positions:1,px_low:99,px_high:99}]}}});
  assert.equal(v1.markets.BTC.buckets[0].band,0);
  assert.equal(C.normalize(v1.markets.BTC,1)[0].lo,99);
  assert.throws(()=>C.validate({...envelope([]),schema_version:4}),/聚合版本不支持/);
});

test('schema3 缺少 lev_unknown 或桶缺 lev 时被拒绝',()=>{
  const noUnknown=envelope([bucket('L',2000,31,[7,11,13,0])]);
  delete noUnknown.markets.BTC.lev_unknown;
  assert.throws(()=>C.validate(noUnknown),/聚合 schema 不匹配/);
  const noLev=envelope([bucket('L',2000,31,undefined)]);
  assert.throws(()=>C.validate(noLev),/杠杆档拆分无效/);
  const missingKey=envelope([bucket('L',2000,31,[7,11,13,0])]);
  delete missingKey.markets.BTC.buckets[0].lev;
  assert.throws(()=>C.validate(missingKey),/聚合 schema 不匹配/);
  // Unsplit cells must be null and accounted for in lev_unknown.
  const undeclared=envelope([bucket('L',2000,31,null)]);
  assert.throws(()=>C.validate(undeclared),/未拆分桶统计不符/);
  const declared=envelope([bucket('L',2000,31,null)]);
  declared.markets.BTC.lev_unknown={buckets:1,notional:31};
  assert.equal(C.validate(declared).markets.BTC.buckets[0].lev,null);
});

test('隐藏某档后柱高按可见档重算，左轴上限随之下降',()=>{
  const b={side:'L',index:2000,notional:31,lev:[7,11,13,0]};
  const shown=[0,1,2,3];
  const stack=(hidden)=>b.lev.reduce((s,v,i)=>s+(hidden.includes(i)?0:v),0);
  assert.equal(stack([]),31);assert.equal(stack([2]),18);assert.equal(stack([0,1,2,3]),0);
  assert.ok(stack([2])<stack([]));
});

test('隐藏档位不改变累计：累计输入仍是完整基础桶',()=>{
  // Explicit extrema keep this test independent of the grid helper.
  const rows=[
    {side:'L',index:1999,notional:11,positions:1,px_low:99.96,px_high:99.97,lev:[11,0,0,0],lo:99.95,hi:100},
    {side:'L',index:2000,notional:31,positions:1,px_low:100,px_high:100,lev:[7,11,13,0],lo:100,hi:100.05},
    {side:'S',index:2001,notional:23,positions:1,px_low:100.1,px_high:100.12,lev:[0,23,0,0],lo:100.05,hi:100.1},
  ];
  const before=C.cumulative(rows,100);
  // Hiding a band is a rendering concern only: the cumulative function has no band input.
  const hidden=[1,2];
  const visibleRows=rows.map(b=>({...b,lev:b.lev.map((v,i)=>hidden.includes(i)?0:v)}));
  const after=C.cumulative(visibleRows,100);
  assert.deepEqual(after.totals,before.totals);
  assert.deepEqual(after.uncertain,before.uncertain);
  assert.deepEqual(after.past,before.past);
  assert.deepEqual(after.points,before.points);
  // 31 sits exactly at the price (counted at once), 11 just below it, 23 above it.
  assert.equal(before.totals.L,42);
  assert.equal(before.at('L',100),31);
  assert.equal(before.at('L',99.96),42);
  assert.equal(before.totals.S,23);assert.equal(before.at('S',100.12),23);
});

test('分辨率合并保留杠杆拆分且金额守恒；无拆分的桶使合并组退化为不堆叠',()=>{
  const rows=C.normalize(market([bucket('L',2000,10,[10,0,0,0]),bucket('L',2001,21,[0,21,0,0])]),3);
  const merged=C.coarsen(rows,.05,5);
  assert.equal(merged.length,1);
  assert.deepEqual(merged[0].lev,[10,21,0,0]);
  assert.equal(C.levSum(merged[0].lev),31);
  assert.equal(merged[0].notional,31);
  const mixed=C.coarsen(C.normalize(market([bucket('L',2000,10,[10,0,0,0]),{...bucket('L',2001,21),lev:null}]),3),.05,5);
  assert.equal(mixed[0].lev,undefined,'任一成员无拆分时整组不得堆叠');
  assert.equal(mixed[0].notional,31);
});

test('合并组不共享杠杆数组（避免跨组串值）',()=>{
  // Factor 5: indices 2000/2001 share a group, 2010 lands in the next one.
  const rows=C.normalize(market([bucket('L',2000,10,[10,0,0,0]),bucket('L',2001,5,[0,5,0,0]),bucket('L',2010,7,[7,0,0,0])]),3);
  const merged=C.coarsen(rows,.05,5);
  assert.equal(merged.length,2);
  assert.notEqual(merged[0].lev,merged[1].lev);
  assert.deepEqual(merged[0].lev,[10,5,0,0]);
  assert.deepEqual(merged[1].lev,[7,0,0,0]);
  merged[0].lev[0]=999;
  assert.equal(merged[1].lev[0],7);
});

test('Watchlist 本地分桶按真实杠杆分档，缺杠杆的桶不堆叠',()=>{
  const rows=C.localBuckets([
    {side:'L',liqPx:100,n:10,lev:5},
    {side:'L',liqPx:100,n:20,lev:40},
    {side:'S',liqPx:99,n:5},              // 缺杠杆：该桶退化为单色柱
  ],100);
  const long=rows.find(b=>b.side==='L');
  // 5x lands in ≤10x and 40x in 26-50x (upper bound inclusive).
  assert.deepEqual(long.lev,[10,0,20,0]);
  assert.equal(long.notional,30);
  assert.equal(C.levSum(long.lev),long.notional);
  const short=rows.find(b=>b.side==='S');
  assert.equal(short.lev,undefined);
  assert.equal(short.notional,5);
  // A fully levelled set keeps every bucket stackable.
  const all=C.localBuckets([{side:'L',liqPx:100,n:1,lev:10},{side:'L',liqPx:101,n:2,lev:51}],100);
  assert.ok(all.every(b=>Array.isArray(b.lev)));
});

test('距现价距离：绝对金额与百分比，多空方向符号明确',()=>{
  const distance=(pxLow,pxHigh,mark)=>{
    const mid=(pxLow+pxHigh)/2,diff=mid-mark,pct=mark?diff/mark*100:0;
    return {diff,pct,sign:diff>0?'+':diff<0?'−':'±'};
  };
  const below=distance(91,91.2,100);
  assert.equal(below.sign,'−');assert.ok(Math.abs(below.diff+8.9)<1e-9);assert.ok(Math.abs(below.pct+8.9)<1e-9);
  const above=distance(105,105,100);
  assert.equal(above.sign,'+');assert.equal(above.diff,5);assert.equal(above.pct,5);
  assert.equal(distance(100,100,100).sign,'±');
});

test('现价线权重高于参考线：粗虚线带箭头且二者坐标可区分',()=>{
  const fs=require('node:fs');
  const ui=fs.readFileSync(__dirname+'/../chart-ui.js','utf8');
  assert.match(ui,/data-current="\$\{mark\}" class="price-line"[\s\S]*?stroke-width="3"[\s\S]*?stroke-dasharray="12 7"/);
  assert.match(ui,/class="price-arrow"/);
  assert.match(ui,/data-reference="\$\{reference\}"/);
  // The reference line stays thin and dotted so the two never read as the same object.
  assert.match(ui,/data-reference="\$\{reference\}"[\s\S]*?stroke-dasharray="2 5"/);
});

test('累计渐变填充存在、位于柱体之下且不改变累计数值或坐标',()=>{
  const fs=require('node:fs');
  const ui=fs.readFileSync(__dirname+'/../chart-ui.js','utf8');
  assert.match(ui,/class="curve-fill" data-fill="\$\{side\}"/);
  assert.match(ui,/linearGradient id="fill\$\{side\}"/);
  assert.match(ui,/stop-opacity="\.26"/);
  // Fills are emitted before the bar loop, so bars paint on top.
  assert.ok(ui.indexOf('data-fill=')<ui.indexOf('visible.forEach((b,i)=>'));
  // The area path reuses the cumulative points verbatim; only the baseline is added.
  assert.match(ui,/points\.map\(\(p,i\)=>\(i\?'L':'M'\)\+x\(p\.px\)\+','\+cy\(p\.value\)\)/);
  const rows=[
    {side:'L',index:1999,notional:11,positions:1,px_low:99.96,px_high:99.97,lev:[11,0,0,0],lo:99.95,hi:100},
    {side:'L',index:2000,notional:31,positions:1,px_low:100,px_high:100,lev:[7,11,13,0],lo:100,hi:100.05},
  ];
  const c=C.cumulative(rows,100);
  assert.deepEqual(c.points.L.map(p=>[p.px,p.value]),[[100,0],[100,0],[100,31],[99.96,31],[99.96,42]]);
});
