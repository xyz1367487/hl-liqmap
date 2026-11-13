/* HL 清算地图 · AGPL-3.0-or-later. SVG, no build or third party runtime. */
let chartWindow=null, chartIdentity='', chartWired=false, panDrag=null, hiddenLev=[];
let hiddenSeries=[], chartContext=null, navDrag=null, tipPinned=false, tipTimer=null, keyboardPrice=null, tipAnchor=null;
// Leverage bands mirror chart-core.js LEV_LIMITS; order is the legend and stacking order.
const LEV_COLORS=['#3f8fdd','#59c2b4','#e0a94b','#cf6a94'];
function levLegend(){
  const C=LiqChart, bands=C.LEV_LABELS;
  return bands.map((label,i)=>{
    const off=hiddenLev.includes(i);
    return `<button type="button" class="lev-key${off?' off':''}" data-lev="${i}" aria-pressed="${off?'false':'true'}" title="点击隐藏/显示 ${label} 杠杆档（累计口径不变）"><i style="background:${LEV_COLORS[i]}"></i>${label}<b data-levsum="${i}"></b></button>`;
  }).join('');
}
function drawChart(){
  if(!cur) return;
  const C=LiqChart, svg=$('priceChart'), frame=$('chartFrame'), tip=$('chartTooltip');
  const watch=$('source').value==='watchlist', m=aggregateSnapshot?.markets[cur.name];
  const reference=m?.reference_mark||Number(cur.ctx.markPx);
  const mark=cur.liveAt?Number(cur.ctx.markPx):reference;
  const version=watch?2:aggregateSnapshot?.schema_version;
  const base=watch?C.localBuckets(wlAll.filter(p=>p.coin===cur.name),reference):C.normalize(m,version);
  const legacy=version===1, factor=+$('resolution').value;
  $('resolution').disabled=legacy;
  const bars=C.coarsen(base,reference*C.FRACTION,factor), cum=C.cumulative(base,mark);
  // Leverage stacking needs a real split on every drawn bucket; otherwise bars stay single-colour.
  const stackable=bars.some(b=>Array.isArray(b.lev));
  const levShown=i=>!hiddenLev.includes(i);
  const stackValue=b=>stackable&&Array.isArray(b.lev)?b.lev.reduce((s,v,i)=>s+(levShown(i)?v:0),0):b.notional;
  const identity=cur.name+':'+$('source').value;
  if(chartIdentity!==identity){chartWindow=null;chartIdentity=identity;keyboardPrice=null;closeReadout();}
  if(!chartWindow){const span=+$('span').value;chartWindow=[Math.max(mark*(1-span),mark*.0001),mark*(1+span)];}
  const [min,max]=chartWindow;
  $('priceMin').value=Number(min.toPrecision(10));$('priceMax').value=Number(max.toPrecision(10));
  const visible=bars.filter(b=>b.hi>=min&&b.lo<=max);
  const showEst=$('estToggle').checked, e=estimate(cur);
  const est=showEst?e.rows.flatMap(r=>[{side:'L',px:r.liqL,notional:r.nL,t:r.t},{side:'S',px:r.liqS,notional:r.nS,t:r.t}]).filter(b=>b.px>=min&&b.px<=max):[];
  $('estLegend').hidden=!showEst;
  const total=side=>base.filter(b=>b.side===side).reduce((n,b)=>n+b.notional,0);
  $('chartTitle').textContent=cur.name+' · 潜在强平名义金额';
  $('chartSubtitle').textContent=(watch?'本机 Watchlist · 独立数据源':legacy?'旧版 schema1 · 原14档区间（不拆分）':'Hyperliquid · 固定参考价网格')+' · '+(legacy?'区间内分布未知':(factor*5)+'bp 显示分辨率')+(stackable?' · 按真实杠杆档堆叠':'');
  $('chartTotal').textContent='全范围多头 $'+fmtUSD(total('L'))+'\n全范围空头 $'+fmtUSD(total('S'));
  $('chartTotal').style.whiteSpace='pre-line';
  const age=aggregateSnapshot?(Date.now()/1000-aggregateSnapshot.generated_at_unix)/60:null;
  const liveAge=cur.liveAt?(Date.now()-cur.liveAt)/1000:Infinity;
  const watchAge=window.watchlistAt?(Date.now()-window.watchlistAt)/60000:Infinity;
  const liveText=Number.isFinite(liveAge)?'行情 '+new Date(cur.liveAt).toLocaleTimeString('zh-CN')+(liveAge>60?'（行情已过期）':''):'行情不可用，暂以分桶参考价定位（非实时现价）';
  $('freshness').className=((watch?watchAge>120:age===null||age>120)||liveAge>60)?'stale':'';
  $('freshness').textContent=(watch?'Watchlist '+(window.watchlistAt?new Date(window.watchlistAt).toLocaleString('zh-CN')+(watchAge>120?' · ⚠ Watchlist已过期（超过2小时）':''):'尚未拉取'):(aggregateSnapshot?'聚合 '+new Date(aggregateSnapshot.generated_at_unix*1000).toLocaleString('zh-CN')+' · '+Math.max(0,Math.floor(age))+'分钟前'+(age>120?' · ⚠ 快照已过期（超过2小时）':''):'尚无聚合快照'))+' ｜ '+liveText+' ｜ 固定分桶参考价 $'+precise(reference);
  // Unsplit buckets are surfaced by amount so a degraded view is never silent.
  const levUnknown=m?.lev_unknown;
  const unknownText=stackable&&levUnknown&&levUnknown.buckets?' 未按杠杆拆分（原始仓位缺杠杆字段）'+levUnknown.buckets+' 桶 / $'+fmtUSD(levUnknown.notional)+'。':'';
  $('chartNote').textContent=(legacy?'旧桶以完整极值区间绘制；多空可能跨参考价，不代表区间内均匀分布。 ':'')+'未纳入累计：跨现价待定位 多 $'+fmtUSD(cum.uncertain.L)+' / 空 $'+fmtUSD(cum.uncertain.S)+'；方向已越过现价 多 $'+fmtUSD(cum.past.L)+' / 空 $'+fmtUSD(cum.past.S)+'（保留原桶，状态未知）。'+unknownText;
  const inView=visible.reduce((sum,b)=>sum+b.notional,0), all=total('L')+total('S');
  $('viewSummary').textContent='与视窗相交的完整桶 '+visible.length+' / '+bars.length+' · 名义 $'+fmtUSD(inView)+' · 完全在窗外 $'+fmtUSD(Math.max(0,all-inView))+'。累计在桶远端极值阶跃计入；完整桶内部不插值。'+(stackable&&hiddenLev.length?' 已隐藏杠杆档 '+hiddenLev.map(i=>C.LEV_LABELS[i]).join('、')+'：柱高与左轴按可见档重算，累计曲线口径不变。':'');
  renderAggregateSummary();
  $('netProg').classList.toggle('load-failed',aggregateState==='error');
  const W=Math.max(640,frame.clientWidth),H=420,left=72,right=W-78,top=48,bottom=365;
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const x=C.linear([min,max],[left,right]);
  const barMax=visible.reduce((v,b)=>Math.max(v,stackValue(b)),est.reduce((v,b)=>Math.max(v,b.notional),1))*1.12;
  const cumMax=Math.max(1,cum.at('L',min),cum.at('S',max))*1.12;
  const y=C.linear([0,barMax],[bottom,top]), cy=C.linear([0,cumMax],[bottom,top]);
  const color=side=>side==='L'?'#4bd6ad':'#ed889d';
  let html='<title>'+escapeChart(cur.name)+' 潜在强平名义金额</title><desc>横轴价格，左轴完整桶美元名义金额，右轴同侧累计美元名义金额。两纵轴独立且均为线性。</desc><defs><clipPath id="plotClip"><rect x="'+left+'" y="'+top+'" width="'+(right-left)+'" height="'+(bottom-top)+'"/></clipPath>';
  for(const side of ['L','S']) html+=`<linearGradient id="fill${side}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${color(side)}" stop-opacity=".09"/><stop offset="100%" stop-color="${color(side)}" stop-opacity="0"/></linearGradient>`;
  html+='</defs>';
  html+=`<text class="axis-title" x="${left}" y="22">本桶名义 · USD（左轴）</text><text class="axis-title" text-anchor="end" x="${right}" y="22">累计潜在强平名义 · USD（右轴）</text>`;
  for(let i=0;i<=4;i++){
    const py=bottom-(bottom-top)*i/4;
    html+=`<line class="grid" x1="${left}" x2="${right}" y1="${py}" y2="${py}"/><text x="${left-12}" y="${py+4}" text-anchor="end">${fmtUSD(barMax*i/4)}</text><text x="${right+12}" y="${py+4}">${fmtUSD(cumMax*i/4)}</text>`;
  }
  for(let i=0;i<=6;i++){
    const px=min+(max-min)*i/6,xx=x(px);
    html+=`<line class="grid" x1="${xx}" x2="${xx}" y1="${top}" y2="${bottom}"/><text x="${xx}" y="${bottom+25}" text-anchor="middle">${fmtPx(px)}</text>`;
  }
  html+=`<text class="axis-title" x="${(left+right)/2}" y="408" text-anchor="middle">价格 · USD →</text><g clip-path="url(#plotClip)">`;
  // Cumulative fills sit under the bars: they add no values and never cover the plot.
  for(const side of ['L','S']){
    const points=cum.points[side];
    if(points.length<2||hiddenSeries.includes(side)) continue;
    const area=points.map((p,i)=>(i?'L':'M')+x(p.px)+','+cy(p.value)).join(' ')+` L${x(points[points.length-1].px)},${cy(0)} L${x(points[0].px)},${cy(0)} Z`;
    html+=`<path class="curve-fill" data-fill="${side}" d="${area}" fill="url(#fill${side})"/>`;
  }
  // Each side gets half of its fixed interval. Legacy extrema intervals may overlap.
  visible.forEach((b,i)=>{
    const lo=Math.max(min,b.lo),hi=Math.min(max,b.hi),width=Math.max(0,x(hi)-x(lo));
    const bx=x(lo)+(b.side==='S'?width/2:0),bw=width/2;
    const label=`${b.side==='L'?'多头':'空头'} ${precise(b.px_low)}至${precise(b.px_high)}美元，本桶${b.notional}美元`;
    if(!stackable||!Array.isArray(b.lev)){
      html+=`<rect class="real-bar" data-bar="${i}" role="graphics-symbol" aria-label="${label}" x="${bx}" y="${y(b.notional)}" width="${bw}" height="${bottom-y(b.notional)}" fill="#a4b1c7" stroke="#a4b1c7"/>`;
      return;
    }
    // Stack in band order so the legend order matches the bottom-to-top order.
    let acc=0;
    html+=`<g class="stack" data-stack="${i}" role="graphics-symbol" aria-label="${label}">`;
    for(let k=0;k<C.LEV_COUNT;k++){
      const value=b.lev[k];
      if(!(value>0)||!levShown(k)) continue;
      const yTop=y(acc+value),yBottom=y(acc);
      html+=`<rect class="real-bar seg" data-bar="${i}" data-seg="${k}" x="${bx}" y="${yTop}" width="${bw}" height="${Math.max(.5,yBottom-yTop)}" fill="${LEV_COLORS[k]}" stroke="${LEV_COLORS[k]}"/>`;
      acc+=value;
    }
    html+='</g>';
  });
  est.forEach((b,i)=>{html+=`<rect class="estimate" data-est="${i}" tabindex="0" x="${x(b.px)-3}" y="${y(b.notional)}" width="6" height="${bottom-y(b.notional)}" fill="${color(b.side)}" stroke="${color(b.side)}"/>`;});
  for(const side of ['L','S']){
    if(hiddenSeries.includes(side)) continue;
    const boundary=side==='L'?min:max,points=cum.points[side];
    const last=points[points.length-1];
    const end=side==='L'?Math.min(boundary,last.px):Math.max(boundary,last.px);
    // Monotone full-range path, extended outward only; SVG clipping handles the window.
    const path=points.map((p,i)=>(i?'L':'M')+x(p.px)+','+cy(p.value)).join(' ')+` L${x(end)},${cy(last.value)}`;
    html+=`<path class="curve" data-curve="${side}" d="${path}" stroke="${color(side)}"/>`;
  }
  // Current price keeps the heavier weight: solid-dashed arrow line above the thin reference grid line.
  html+=`<line data-reference="${reference}" x1="${x(reference)}" x2="${x(reference)}" y1="${top}" y2="${bottom}" stroke="#91a1b9" stroke-dasharray="2 5"/>`;
  if(mark>=min&&mark<=max){
    const mx=x(mark);
    html+=`<line data-current="${mark}" class="price-line" x1="${mx}" x2="${mx}" y1="${top+18}" y2="${bottom}" stroke="#efca7b" stroke-width="3" stroke-dasharray="12 7"/><path class="price-arrow" d="M${mx},${top+2} L${mx-8},${top+20} L${mx+8},${top+20} Z" fill="#efca7b"/>`;
  }
  html+='</g><g id="crosshair" hidden pointer-events="none"></g>';
  if(mark>=min&&mark<=max) html+=`<text class="price-label" x="${Math.min(right-96,Math.max(left+4,x(mark)+12))}" y="34">${Number.isFinite(liveAge)?'行情':'参考定位'} $${fmtPx(mark)}</text>`;
  if(!base.length) html+=`<text x="${(left+right)/2}" y="240" text-anchor="middle">${watch?'Watchlist 尚无该币有效强平价，请先拉取仓位':aggregateEmptyText()}</text>`;
  else if(!visible.length) html+=`<text x="${(left+right)/2}" y="240" text-anchor="middle">当前价格范围无真实桶，请扩大范围</text>`;
  svg.innerHTML=html;
  if(!tipPinned)tip.hidden=true;
  const legend=$('levLegend');
  if(legend){
    legend.innerHTML=stackable?levLegend():'';
    legend.hidden=!stackable;
    if(stackable){
      const sums=[0,0,0,0];
      for(const b of visible) if(Array.isArray(b.lev)) for(let k=0;k<C.LEV_COUNT;k++) sums[k]+=b.lev[k];
      for(let k=0;k<C.LEV_COUNT;k++){
        const node=legend.querySelector(`[data-levsum="${k}"]`);
        if(node) node.textContent='$'+fmtUSD(sums[k]);
      }
    }
  }
  window.chartInspection={coin:cur.name,version,mark,reference,window:[...chartWindow],baseCount:base.length,visibleCount:visible.length,totals:{L:total('L'),S:total('S')},cumulative: cum.totals,uncertain:cum.uncertain,past:cum.past,barMax,cumMax,stackable,hiddenLev:[...hiddenLev],levUnknown:levUnknown?{...levUnknown}:null};
  chartContext={C,svg,frame,tip,base,bars,visible,est,cum,mark,reference,legacy,factor,watch,stackable,levShown,W,H,left,right,top,bottom,x,min,max};
  renderNavigator();
  wireChart();
  if((tipPinned||tip.matches(':hover,:focus-within'))&&keyboardPrice!==null)locatePrice(keyboardPrice);
}
function closeReadout(){
  clearTimeout(tipTimer);tipPinned=false;
  $('chartTooltip').hidden=true;
  const cross=$('crosshair');if(cross) cross.setAttribute('hidden','');
}
function deferClose(){
  clearTimeout(tipTimer);
  tipTimer=setTimeout(()=>{if(!tipPinned&&!$('chartTooltip').matches(':hover,:focus-within'))closeReadout();},240);
}
function placeReadout(px,py){
  tipAnchor=[px,py];
  const tip=$('chartTooltip');
  tip.style.left='8px';tip.style.top='8px';
  const {width,height}=tip.getBoundingClientRect(),pad=8;
  const plot=$('chartFrame').getBoundingClientRect();
  const floor=Math.max(pad,Math.min(plot.top,innerHeight-height-pad));
  let left=px+18,top=py+16;
  if(left+width>innerWidth-pad) left=px-width-18;
  if(top+height>innerHeight-pad) top=py-height-16;
  tip.style.left=Math.max(pad,Math.min(left,innerWidth-width-pad))+'px';
  tip.style.top=Math.max(floor,Math.min(top,innerHeight-height-pad))+'px';
}
function locatePrice(price,clientX,clientY){
  if(!chartContext||panDrag||navDrag) return;
  const c=chartContext,{C,svg,base,bars,cum,mark,reference,legacy,factor,watch,x,left,right,top,bottom,W,H}=c;
  if(price<c.min||price>c.max) return;
  clearTimeout(tipTimer);keyboardPrice=price;
  const xx=x(price),cross=$('crosshair');
  cross.removeAttribute('hidden');
  cross.innerHTML=`<line class="locator" x1="${xx}" x2="${xx}" y1="${top}" y2="${bottom}"/><rect x="${Math.max(left,Math.min(right-108,xx-54))}" y="${bottom+3}" width="108" height="24" rx="4"/><text text-anchor="middle" x="${Math.max(left+54,Math.min(right-54,xx))}" y="${bottom+19}">$${precise(price)}</text>`;
  const loaded=watch?Boolean(window.watchlistAt):Boolean(aggregateSnapshot);
  const hit=C.hitPrice(bars,price,reference*C.FRACTION,factor,legacy);
  const fullLo=base.reduce((v,b)=>Math.min(v,b.lo),Infinity),fullHi=base.reduce((v,b)=>Math.max(v,b.hi),-Infinity);
  // Absence is zero only inside a loaded grid's observed extent; never on failed initial load.
  const knownEmpty=loaded&&!legacy&&price>=fullLo&&price<fullHi;
  const summary=[],details=[];
  if(hit.rows.length){
    const interval=legacy?null:hit.interval;
    if(interval)summary.push(`价格区间 $${precise(interval[0])} — $${precise(interval[1])}（右端不含）`);
    for(const b of hit.rows){
      const side=b.side==='L'?'多头':'空头',far=b.side==='L'?b.px_low:b.px_high;
      if(legacy)summary.push(`原桶区间 $${precise(b.lo)} — $${precise(b.hi)}（区间细节未知）`);
      summary.push(`${side} · 该桶名义 USD $${money(b.notional)}`);
      const mid=legacy?(b.lo+b.hi)/2:(interval[0]+interval[1])/2;
      const diff=Math.abs(mid-mark),live=cur.liveAt?'实时现价':'分桶参考定位价（非实时）';
      summary.push(`距${live} $${money(diff)} / ${(diff/mark*100).toFixed(2)}%（桶中值${mid>=mark?'高于':'低于'}）`);
      summary.push(`相应累计${side} USD $${money(cum.at(b.side,far))}`);
      details.push(`${side} · ${b.positions} 仓 · 桶内强平价 $${precise(b.px_low)} — $${precise(b.px_high)}`);
      if(Array.isArray(b.lev)) details.push(C.LEV_LABELS.map((label,k)=>`${label} $${money(b.lev[k])}${hiddenLev.includes(k)?'（已隐藏）':''}`).join(' · '));
      else details.push('无真实杠杆拆分：灰色柱，不推算杠杆档。');
      details.push(b.px_low<mark&&b.px_high>mark?'跨现价桶：区间内金额不可定位。':b.side==='L'&&b.px_high>mark||b.side==='S'&&b.px_low<mark?'方向已越过现价，仍保留原桶，未认定已爆仓。':'累计在完整基础桶远端极值阶跃计入，包含视窗外近端桶。');
    }
  }else{
    if(hit.interval)summary.push(`价格区间 $${precise(hit.interval[0])} — $${precise(hit.interval[1])}（右端不含）`);
    else summary.push(`定位价格 $${precise(price)} · 原区间细节未知`);
    summary.push(!loaded?(watch?'Watchlist 尚未拉取':aggregateEmptyText()):knownEmpty?'无仓 · 该桶名义 USD $0.00':legacy?'该位置无原桶覆盖；区间细节未知':'无仓 · 已加载分布范围之外，无可读桶');
    summary.push(`距${cur.liveAt?'实时现价':'参考定位价（非实时）'} $${money(Math.abs(price-mark))} / ${(Math.abs(price-mark)/mark*100).toFixed(2)}%`);
    if(loaded)summary.push(`定位价累计 USD 多头 $${money(cum.at('L',price))} / 空头 $${money(cum.at('S',price))}`);
  }
  details.push('累计含全部杠杆档与完整基础桶；隐藏杠杆仅影响柱体和左轴。累计开关仅隐藏线与填充，右轴数值不变。');
  details.push(legacy?'schema1 按原区间展示，不伪造细分。':'显示分辨率 '+factor*5+'bp；按真实网格 index 命中，不吸附最近柱。');
  $('tipSummary').textContent=summary.join('\n');$('tipLong').textContent=details.join('\n');
  $('chartTooltip').hidden=false;
  const box=svg.getBoundingClientRect();
  placeReadout(clientX??box.left+xx/W*box.width,clientY??box.top+H/2/H*box.height);
  window.chartReadout={price,interval:hit.interval,rows:hit.rows.map(b=>({side:b.side,index:b.index,notional:b.notional})),knownEmpty,loaded};
}
function renderNavigator(){
  const c=chartContext,{C,base,mark}=c;
  const domain=navDrag?.domain||C.overviewDomain(base,mark,chartWindow);
  c.domain=domain;
  const scale=C.linear(domain,[0,1000]),columns=new Map();
  for(const b of base){const col=Math.max(0,Math.min(999,Math.floor(scale((b.lo+b.hi)/2))));columns.set(col,(columns.get(col)||0)+b.notional);}
  const peak=Math.max(1,...columns.values());
  $('overview').innerHTML=[...columns].map(([col,value])=>`<path d="M${col+.5},48 V${48-44*value/peak}" stroke="#93afd2" stroke-width="1"/>`).join('');
  const percent=p=>(p-domain[0])/(domain[1]-domain[0])*100;
  const lo=percent(chartWindow[0]),hi=percent(chartWindow[1]);
  $('navSelection').style.left=lo+'%';$('navSelection').style.width=(hi-lo)+'%';
  for(const [id,value] of [['navLow',chartWindow[0]],['navHigh',chartWindow[1]]]){
    const node=$(id);node.style.left=percent(value)+'%';
    node.setAttribute('aria-valuemin',id==='navLow'?domain[0]:chartWindow[0]);
    node.setAttribute('aria-valuemax',id==='navHigh'?domain[1]:chartWindow[1]);
    node.setAttribute('aria-valuenow',value);node.setAttribute('aria-valuetext','$'+precise(value));
    node.disabled=!base.length;
  }
  $('navSelection').disabled=!base.length;
  $('navBounds').textContent=`全分布 $${precise(domain[0])} — $${precise(domain[1])} · 选区 $${precise(chartWindow[0])} — $${precise(chartWindow[1])}`;
  window.chartInspection.domain=[...domain];window.chartInspection.hiddenSeries=[...hiddenSeries];
}
function zoomChart(scale){
  if(!chartWindow)return;
  const center=(chartWindow[0]+chartWindow[1])/2,half=(chartWindow[1]-chartWindow[0])*scale/2;
  chartWindow=[Math.max(0,center-half),center+half];closeReadout();drawChart();
}
function wireChart(){
  if(chartWired)return;chartWired=true;
  const svg=$('priceChart'),tip=$('chartTooltip');
  const pointerPrice=event=>{
    const c=chartContext,box=svg.getBoundingClientRect();
    const xx=(event.clientX-box.left)/box.width*c.W,yy=(event.clientY-box.top)/box.height*c.H;
    return xx>=c.left&&xx<=c.right&&yy>=c.top&&yy<=c.bottom?c.min+(xx-c.left)/(c.right-c.left)*(c.max-c.min):null;
  };
  svg.onpointerdown=event=>{
    if(event.button!==0||pointerPrice(event)===null)return;
    const box=svg.getBoundingClientRect(),c=chartContext;
    panDrag={startX:event.clientX,startY:event.clientY,view:[...chartWindow],width:box.width*(c.right-c.left)/c.W,moved:false,pointerId:event.pointerId};
    closeReadout();svg.setPointerCapture?.(event.pointerId);
  };
  svg.onpointermove=event=>{
    if(panDrag){
      const dx=event.clientX-panDrag.startX;
      if(!panDrag.moved&&Math.abs(dx)<4)return;
      panDrag.moved=true;svg.classList.add('dragging');closeReadout();
      chartWindow=LiqChart.moveRange(panDrag.view,-dx/panDrag.width*(panDrag.view[1]-panDrag.view[0]));drawChart();return;
    }
    if(tipPinned)return;
    const estimated=event.target.closest('[data-est]');
    if(estimated){showEstimate(estimated,event);return;}
    const price=pointerPrice(event);if(price===null){deferClose();return;}
    locatePrice(price,event.clientX,event.clientY);
  };
  const endPan=event=>{
    if(!panDrag)return;
    const drag=panDrag;panDrag=null;svg.classList.remove('dragging');
    if(svg.hasPointerCapture?.(event.pointerId))svg.releasePointerCapture(event.pointerId);
    if(event.type!=='pointercancel'&&!drag.moved){const price=pointerPrice(event);if(price!==null){tipPinned=true;locatePrice(price,event.clientX,event.clientY);}}
  };
  svg.onfocusin=event=>{if(event.target.matches('[data-est]'))showEstimate(event.target,event);};
  svg.onpointerup=endPan;svg.onpointercancel=endPan;svg.onlostpointercapture=()=>{panDrag=null;svg.classList.remove('dragging');};
  svg.onpointerleave=()=>{if(!panDrag)deferClose();};
  svg.onkeydown=event=>{
    if(event.key==='Escape'){closeReadout();return;}
    if(event.key==='Enter'){tipPinned=true;locatePrice(keyboardPrice??(chartWindow[0]+chartWindow[1])/2);$('closeTooltip').focus();event.preventDefault();return;}
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    const c=chartContext,delta=c.legacy?(c.max-c.min)/100:c.reference*LiqChart.FRACTION*c.factor;
    keyboardPrice=event.key==='Home'?c.min:event.key==='End'?c.max:Math.max(c.min,Math.min(c.max,(keyboardPrice??(c.min+c.max)/2)+(event.key==='ArrowRight'?delta:-delta)));
    tipPinned=true;locatePrice(keyboardPrice);event.preventDefault();
  };
  tip.onpointerenter=()=>clearTimeout(tipTimer);tip.onpointerleave=deferClose;
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeReadout();});
  tip.onkeydown=event=>{if(event.key==='Escape'){closeReadout();svg.focus();}};
  tip.onfocusin=()=>clearTimeout(tipTimer);tip.onfocusout=deferClose;
  $('tipDetails').ontoggle=()=>{if(!tip.hidden&&tipAnchor)placeReadout(...tipAnchor);};
  $('tipDetails').onclick=()=>{tipPinned=true;};
  $('closeTooltip').onclick=()=>{closeReadout();svg.focus();};
  svg.addEventListener('wheel',event=>{if(!event.ctrlKey&&!event.metaKey)return;event.preventDefault();zoomChart(event.deltaY>0?1.15:1/1.15);},{passive:false});
  $('source').onchange=()=>{closeReadout();drawChart();};$('resolution').onchange=()=>{closeReadout();drawChart();};
  $('span').onchange=()=>{chartWindow=null;closeReadout();drawChart();};
  $('resetView').onclick=()=>{chartWindow=null;closeReadout();drawChart();};
  $('zoomIn').onclick=()=>zoomChart(.65);$('zoomOut').onclick=()=>zoomChart(1/.65);
  $('applyRange').onclick=()=>{
    const lo=+$('priceMin').value,hi=+$('priceMax').value;
    if(Number.isFinite(lo)&&Number.isFinite(hi)&&lo>=0&&hi>lo){chartWindow=[lo,hi];closeReadout();drawChart();}
    else{$('chartNote').textContent='请输入有效价格区间：0 ≤ 下限 < 上限。';$('chartNote').closest('details').open=true;}
  };
  $('levLegend').onclick=event=>{
    const key=event.target.closest('[data-lev]');if(!key)return;
    const band=+key.dataset.lev;hiddenLev=hiddenLev.includes(band)?hiddenLev.filter(i=>i!==band):[...hiddenLev,band].sort((a,b)=>a-b);
    closeReadout();drawChart();$('levLegend').querySelector(`[data-lev="${band}"]`)?.focus();
  };
  document.querySelectorAll('[data-series]').forEach(button=>button.onclick=()=>{
    const side=button.dataset.series;hiddenSeries=hiddenSeries.includes(side)?hiddenSeries.filter(s=>s!==side):[...hiddenSeries,side];
    button.setAttribute('aria-pressed',!hiddenSeries.includes(side));closeReadout();drawChart();
  });
  let resizePending=false;
  const resize=()=>{
    if(resizePending)return;resizePending=true;
    requestAnimationFrame(()=>{resizePending=false;if(chartContext&&chartContext.W!==Math.max(640,$('chartFrame').clientWidth))drawChart();});
  };
  if(typeof ResizeObserver!=='undefined'){
    new ResizeObserver(resize).observe($('chartFrame'));
    new ResizeObserver(()=>{if(!tip.hidden&&tipAnchor)placeReadout(...tipAnchor);}).observe(tip);
  }else window.addEventListener('resize',resize);
  for(const id of ['navLow','navHigh','navSelection']){
    const node=$(id);
    node.onpointerdown=event=>{
      if(event.button!==0)return;
      closeReadout();const box=$('navigator').getBoundingClientRect();
      navDrag={id,startX:event.clientX,width:box.width,view:[...chartWindow],domain:[...chartContext.domain]};node.setPointerCapture(event.pointerId);
    };
    node.onpointermove=event=>{
      if(!navDrag||navDrag.id!==id)return;
      const d=navDrag,delta=(event.clientX-d.startX)/d.width*(d.domain[1]-d.domain[0]);
      changeNavigator(id,d.view,delta,d.domain);drawChart();
    };
    const end=()=>{navDrag=null;};node.onpointerup=end;node.onpointercancel=end;node.onlostpointercapture=end;
    node.onkeydown=event=>{
      const keys=['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','PageUp','PageDown','Home','End'];if(!keys.includes(event.key))return;
      // Keyboard movement follows the visible window, so a far outlier cannot collapse it in one step.
      const domain=chartContext.domain,view=[...chartWindow];
      const step=(view[1]-view[0])/(event.shiftKey?10:100);
      let delta=step*(['ArrowLeft','ArrowDown','PageDown'].includes(event.key)?-1:1)*(event.key.startsWith('Page')?10:1);
      if(event.key==='Home')delta=domain[0]-(id==='navHigh'?view[1]:view[0]);
      if(event.key==='End')delta=domain[1]-(id==='navLow'?view[0]:view[1]);
      changeNavigator(id,view,delta,domain);closeReadout();drawChart();event.preventDefault();
    };
  }
}
function showEstimate(node,event){
  const b=chartContext.est[+node.dataset.est];if(!b)return;
  const cross=$('crosshair');if(cross)cross.setAttribute('hidden','');
  $('tipSummary').textContent=`假设估算 · ${b.side==='L'?'多头':'空头'} · ${b.t}x
假设强平价 $${precise(b.px)}
估算名义 USD $${money(b.notional)}`;
  $('tipLong').textContent='OI × 杠杆权重 × 多空假设。不是真实仓位，不计入累计。';
  $('chartTooltip').hidden=false;
  const box=node.getBoundingClientRect();placeReadout(event.clientX??box.x,event.clientY??box.y);
}
function changeNavigator(id,view,delta,domain){
  const gap=Math.max((domain[1]-domain[0])*1e-9,Number.EPSILON);
  if(id==='navSelection')chartWindow=LiqChart.moveRange(view,delta,domain);
  else if(id==='navLow')chartWindow=[Math.max(domain[0],Math.min(view[1]-gap,view[0]+delta)),view[1]];
  else chartWindow=[view[0],Math.min(domain[1],Math.max(view[0]+gap,view[1]+delta))];
}
function precise(n){return Number(n).toLocaleString('en-US',{maximumSignificantDigits:10});}
function money(n){return Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}
function escapeChart(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
