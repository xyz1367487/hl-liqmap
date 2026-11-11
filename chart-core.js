/* HL 清算地图 · AGPL-3.0-or-later. Pure data/coordinate logic shared by UI and tests. */
(function(root){
  'use strict';
  const FRACTION=0.0005;
  function gridIndex(px,step){
    // Exact ratio of shortest decimal JSON numbers, consistent with Python Decimal.
    const parts=n=>{const [mantissa,exp='0']=String(n).toLowerCase().split('e'),[whole,frac='']=mantissa.split('.');return [BigInt(whole+frac),Number(exp)-frac.length];};
    const [a,ae]=parts(px),[b,be]=parts(step),shift=ae-be;
    return Number(shift>=0?a*10n**BigInt(shift)/b:a/(b*10n**BigInt(-shift)));
  }
  function validate(s){
    const exact=(o,fields)=>{if(!o||typeof o!=='object'||Array.isArray(o)||Object.keys(o).sort().join('|')!==fields.split(' ').filter(Boolean).sort().join('|')) throw Error('聚合 schema 不匹配');};
    const num=(v,positive=false)=>{if(typeof v!=='number'||!Number.isFinite(v)||v<0||(positive&&v===0)) throw Error('聚合数值无效');};
    exact(s,'schema_version generated_at_unix privacy coin_list markets');
    if(![1,2].includes(s.schema_version)) throw Error('聚合版本不支持');
    num(s.generated_at_unix,true); exact(s.privacy,'scope buckets');
    if(s.privacy.scope!=='aggregate_only'||s.privacy.buckets!=='all_nonempty') throw Error('聚合策略不匹配');
    exact(s.coin_list,'updated caliber threshold coins');
    if(typeof s.coin_list.updated!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(s.coin_list.updated)||s.coin_list.caliber!=='avg_7d'||s.coin_list.threshold!==5000000||!Array.isArray(s.coin_list.coins)) throw Error('币种口径不匹配');
    const names=new Set();
    for(const c of s.coin_list.coins){exact(c,'n v');if(typeof c.n!=='string'||!/^[A-Za-z0-9@:_./-]{1,64}$/.test(c.n)||names.has(c.n)) throw Error('币名无效');num(c.v);names.add(c.n);}
    exact(s.markets,[...names].join(' '));
    for(const m of Object.values(s.markets)){
      const v2=s.schema_version===2; exact(m,v2?'reference_mark bucket_step buckets':'reference_mark buckets');num(m.reference_mark,true);
      if(v2){num(m.bucket_step,true);if(m.bucket_step!==m.reference_mark*FRACTION) throw Error('固定网格步长无效');}
      if(!Array.isArray(m.buckets)) throw Error('桶列表无效');
      const seen=new Set();
      for(const b of m.buckets){
        const field=v2?'index':'band';exact(b,`side ${field} notional positions px_low px_high`);
        const k=b.side+':'+b[field];
        if(!['L','S'].includes(b.side)||!Number.isSafeInteger(b[field])||b[field]<0||(!v2&&b.band>=14)||seen.has(k)||!Number.isSafeInteger(b.positions)||b.positions<=0) throw Error('桶无效');
        seen.add(k); num(b.notional);num(b.px_low,true);num(b.px_high,true);
        if(b.px_low>b.px_high) throw Error('价格区间无效');
        if(v2&&(gridIndex(b.px_low,m.bucket_step)!==b.index||gridIndex(b.px_high,m.bucket_step)!==b.index)) throw Error('价格超出固定桶');
      }
    }
    if(/0x[a-fA-F0-9]{40}/.test(JSON.stringify(s))) throw Error('公开输出含地址');
    return s;
  }
  function normalize(m,version){
    if(!m) return [];
    return m.buckets.map((b,i)=>({...b,id:`${b.side}:${b.index??b.band}:${i}`,lo:version===2?b.index*m.bucket_step:b.px_low,hi:version===2?(b.index+1)*m.bucket_step:b.px_high,legacy:version===1}));
  }
  // Coarsening never invents sub-buckets; cumulative calculations always use base cells.
  function coarsen(rows,step,factor){
    if(factor===1||!step||rows.some(b=>b.legacy)) return rows.map(b=>({...b}));
    const groups=new Map();
    for(const b of rows){
      const index=Math.floor(b.index/factor), key=b.side+':'+index;
      if(!groups.has(key)) groups.set(key,{...b,id:key,index,lo:index*step*factor,hi:(index+1)*step*factor,notional:0,positions:0,px_low:Infinity,px_high:0});
      const g=groups.get(key);g.notional+=b.notional;g.positions+=b.positions;g.px_low=Math.min(g.px_low,b.px_low);g.px_high=Math.max(g.px_high,b.px_high);
    }
    return [...groups.values()].sort((a,b)=>a.lo-b.lo||a.side.localeCompare(b.side));
  }
  function localBuckets(positions,reference){
    const step=reference*FRACTION,groups=new Map();
    for(const p of positions){
      if(!(p.liqPx>0&&Number.isFinite(p.liqPx)&&p.n>=0&&Number.isFinite(p.n))) continue;
      const index=gridIndex(p.liqPx,step),key=p.side+':'+index;
      if(!groups.has(key)) groups.set(key,{side:p.side,index,notional:0,positions:0,px_low:p.liqPx,px_high:p.liqPx});
      const b=groups.get(key);b.notional+=p.n;b.positions++;b.px_low=Math.min(b.px_low,p.liqPx);b.px_high=Math.max(b.px_high,p.liqPx);
    }
    return normalize({bucket_step:step,buckets:[...groups.values()]},2);
  }
  function cumulative(rows,mark){
    const eligible={L:[],S:[]},uncertain={L:0,S:0},past={L:0,S:0};
    for(const b of rows){
      // Extrema (not grid edges) decide whether the entire bucket is on one side.
      if(b.side==='L'&&b.px_high<=mark) eligible.L.push(b);
      else if(b.side==='S'&&b.px_low>=mark) eligible.S.push(b);
      else if(b.px_low<=mark&&b.px_high>=mark) uncertain[b.side]+=b.notional;
      else past[b.side]+=b.notional;
    }
    const points={L:[{px:mark,value:0}],S:[{px:mark,value:0}]};
    const totals={L:0,S:0};
    for(const side of ['L','S']){
      // Include a bucket only at its far observed edge: no fabricated allocation within it.
      const edge=b=>side==='L'?b.px_low:b.px_high;
      const ordered=eligible[side].slice().sort((a,b)=>side==='L'?edge(b)-edge(a):edge(a)-edge(b));
      for(let i=0;i<ordered.length;){
        const px=edge(ordered[i]);let value=0;
        do{value+=ordered[i++].notional;}while(i<ordered.length&&edge(ordered[i])===px);
        points[side].push({px,value:totals[side]});totals[side]+=value;points[side].push({px,value:totals[side]});
      }
    }
    const at=(side,price)=>eligible[side].reduce((sum,b)=>sum+((side==='L'?b.px_low>=price:b.px_high<=price)?b.notional:0),0);
    return {points,totals,uncertain,past,at};
  }
  function linear(domain,range){
    if(!(domain[1]>domain[0])) throw Error('无效坐标范围');
    return value=>range[0]+(value-domain[0])/(domain[1]-domain[0])*(range[1]-range[0]);
  }
  const api={FRACTION,gridIndex,validate,normalize,coarsen,localBuckets,cumulative,linear};
  if(typeof module!=='undefined'&&module.exports) module.exports=api;
  root.LiqChart=api;
})(typeof globalThis!=='undefined'?globalThis:this);
