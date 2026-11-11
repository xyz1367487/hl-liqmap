/* HL 清算地图 · AGPL-3.0-or-later. SVG, no build or third party runtime. */
let chartWindow=null, chartIdentity='', chartWired=false;
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
  const identity=cur.name+':'+$('source').value;
  if(chartIdentity!==identity){chartWindow=null;chartIdentity=identity;}
  if(!chartWindow){const span=+$('span').value;chartWindow=[Math.max(mark*(1-span),mark*.0001),mark*(1+span)];}
  const [min,max]=chartWindow;
  $('priceMin').value=Number(min.toPrecision(10));$('priceMax').value=Number(max.toPrecision(10));
  const visible=bars.filter(b=>b.hi>=min&&b.lo<=max);
  const showEst=$('estToggle').checked, e=estimate(cur);
  const est=showEst?e.rows.flatMap(r=>[{side:'L',px:r.liqL,notional:r.nL,t:r.t},{side:'S',px:r.liqS,notional:r.nS,t:r.t}]).filter(b=>b.px>=min&&b.px<=max):[];
  $('estLegend').hidden=!showEst;
  const total=side=>base.filter(b=>b.side===side).reduce((n,b)=>n+b.notional,0);
  $('chartTitle').textContent=cur.name+' · 潜在强平名义金额';
  $('chartSubtitle').textContent=(watch?'本机 Watchlist · 独立数据源':legacy?'旧版 schema1 · 原14档区间（不拆分）':'Hyperliquid · 固定参考价网格')+' · '+(legacy?'区间内分布未知':(factor*5)+'bp 显示分辨率');
  $('chartTotal').textContent='全范围多头 $'+fmtUSD(total('L'))+'\n全范围空头 $'+fmtUSD(total('S'));
  $('chartTotal').style.whiteSpace='pre-line';
  const age=aggregateSnapshot?(Date.now()/1000-aggregateSnapshot.generated_at_unix)/60:null;
  const liveAge=cur.liveAt?(Date.now()-cur.liveAt)/1000:Infinity;
  const watchAge=window.watchlistAt?(Date.now()-window.watchlistAt)/60000:Infinity;
  const liveText=Number.isFinite(liveAge)?'行情 '+new Date(cur.liveAt).toLocaleTimeString('zh-CN')+(liveAge>60?'（行情已过期）':''):'行情不可用，暂以分桶参考价定位（非实时现价）';
  $('freshness').className=((watch?watchAge>120:age===null||age>120)||liveAge>60)?'stale':'';
  $('freshness').textContent=(watch?'Watchlist '+(window.watchlistAt?new Date(window.watchlistAt).toLocaleString('zh-CN')+(watchAge>120?' · ⚠ Watchlist已过期（超过2小时）':''):'尚未拉取'):(aggregateSnapshot?'聚合 '+new Date(aggregateSnapshot.generated_at_unix*1000).toLocaleString('zh-CN')+' · '+Math.max(0,Math.floor(age))+'分钟前'+(age>120?' · ⚠ 快照已过期（超过2小时）':''):'尚无聚合快照'))+' ｜ '+liveText+' ｜ 固定分桶参考价 $'+precise(reference);
  $('chartNote').textContent=(legacy?'旧桶以完整极值区间绘制；多空可能跨参考价，不代表区间内均匀分布。 ':'')+'未纳入累计：跨现价待定位 多 $'+fmtUSD(cum.uncertain.L)+' / 空 $'+fmtUSD(cum.uncertain.S)+'；方向已越过现价 多 $'+fmtUSD(cum.past.L)+' / 空 $'+fmtUSD(cum.past.S)+'（保留原桶，状态未知）。';
  const inView=visible.reduce((sum,b)=>sum+b.notional,0), all=total('L')+total('S');
  $('viewSummary').textContent='与视窗相交的完整桶 '+visible.length+' / '+bars.length+' · 名义 $'+fmtUSD(inView)+' · 完全在窗外 $'+fmtUSD(Math.max(0,all-inView))+'。累计在桶远端极值阶跃计入；完整桶内部不插值。';
  renderAggregateSummary();
  const W=1120,H=520,left=82,right=1035,top=56,bottom=448;
  const x=C.linear([min,max],[left,right]);
  const barMax=visible.reduce((v,b)=>Math.max(v,b.notional),est.reduce((v,b)=>Math.max(v,b.notional),1))*1.12;
  const cumMax=Math.max(1,cum.at('L',min),cum.at('S',max))*1.12;
  const y=C.linear([0,barMax],[bottom,top]), cy=C.linear([0,cumMax],[bottom,top]);
  const color=side=>side==='L'?'#4bd6ad':'#ed889d';
  let html='<title>'+escapeChart(cur.name)+' 潜在强平名义金额</title><desc>横轴价格，左轴完整桶美元名义金额，右轴同侧累计美元名义金额。两纵轴独立且均为线性。</desc><defs><clipPath id="plotClip"><rect x="'+left+'" y="'+top+'" width="'+(right-left)+'" height="'+(bottom-top)+'"/></clipPath></defs>';
  html+=`<text class="axis-title" x="${left}" y="22">本桶名义 · USD（左轴）</text><text class="axis-title" text-anchor="end" x="${right}" y="22">累计潜在强平名义 · USD（右轴）</text>`;
  for(let i=0;i<=4;i++){
    const py=bottom-(bottom-top)*i/4;
    html+=`<line class="grid" x1="${left}" x2="${right}" y1="${py}" y2="${py}"/><text x="${left-12}" y="${py+4}" text-anchor="end">${fmtUSD(barMax*i/4)}</text><text x="${right+12}" y="${py+4}">${fmtUSD(cumMax*i/4)}</text>`;
  }
  for(let i=0;i<=6;i++){
    const px=min+(max-min)*i/6,xx=x(px);
    html+=`<line class="grid" x1="${xx}" x2="${xx}" y1="${top}" y2="${bottom}"/><text x="${xx}" y="${bottom+25}" text-anchor="middle">${fmtPx(px)}</text>`;
  }
  html+=`<text class="axis-title" x="${(left+right)/2}" y="505" text-anchor="middle">价格 · USD →</text><g clip-path="url(#plotClip)">`;
  // Each side gets half of its fixed interval. Legacy extrema intervals may overlap.
  visible.forEach((b,i)=>{
    const lo=Math.max(min,b.lo),hi=Math.min(max,b.hi),width=Math.max(.8,x(hi)-x(lo));
    const bx=x(lo)+(b.side==='S'?width/2:0),bw=Math.max(.5,width/2-.25);
    html+=`<rect class="real-bar" data-bar="${i}" tabindex="0" role="graphics-symbol" aria-label="${b.side==='L'?'多头':'空头'} ${precise(b.px_low)}至${precise(b.px_high)}美元，本桶${b.notional}美元" x="${bx}" y="${y(b.notional)}" width="${bw}" height="${bottom-y(b.notional)}" fill="${color(b.side)}" stroke="${color(b.side)}"/>`;
  });
  est.forEach((b,i)=>{html+=`<rect class="estimate" data-est="${i}" tabindex="0" x="${x(b.px)-3}" y="${y(b.notional)}" width="6" height="${bottom-y(b.notional)}" fill="${color(b.side)}" stroke="${color(b.side)}"/>`;});
  for(const side of ['L','S']){
    const boundary=side==='L'?min:max,points=cum.points[side];
    const last=points[points.length-1];
    const end=side==='L'?Math.min(boundary,last.px):Math.max(boundary,last.px);
    // Monotone full-range path, extended outward only; SVG clipping handles the window.
    const path=points.map((p,i)=>(i?'L':'M')+x(p.px)+','+cy(p.value)).join(' ')+` L${x(end)},${cy(last.value)}`;
    html+=`<path class="curve" data-curve="${side}" d="${path}" stroke="${color(side)}"/>`;
  }
  html+=`<line data-reference="${reference}" x1="${x(reference)}" x2="${x(reference)}" y1="${top}" y2="${bottom}" stroke="#91a1b9" stroke-dasharray="2 5"/><line data-current="${mark}" x1="${x(mark)}" x2="${x(mark)}" y1="${top}" y2="${bottom}" stroke="#efca7b" stroke-width="1.5" stroke-dasharray="7 5"/></g>`;
  if(mark>=min&&mark<=max) html+=`<text x="${Math.min(right-100,Math.max(left,x(mark)+6))}" y="42" style="fill:#efca7b">${Number.isFinite(liveAge)?'行情':'参考定位'} $${fmtPx(mark)}</text>`;
  if(!base.length) html+=`<text x="${(left+right)/2}" y="240" text-anchor="middle">${watch?'Watchlist 尚无该币有效强平价，请先拉取仓位':'该币暂无真实聚合桶'}</text>`;
  else if(!visible.length) html+=`<text x="${(left+right)/2}" y="240" text-anchor="middle">当前价格范围无真实桶，请扩大范围</text>`;
  svg.innerHTML=html;tip.hidden=true;
  window.chartInspection={coin:cur.name,version,mark,reference,window:[...chartWindow],baseCount:base.length,visibleCount:visible.length,totals:{L:total('L'),S:total('S')},cumulative: cum.totals,uncertain:cum.uncertain,past:cum.past,barMax,cumMax};
  function tooltip(event){
    const target=event.target.closest('[data-bar],[data-est]');if(!target){tip.hidden=true;return;}
    const estimated=target.hasAttribute('data-est'),b=estimated?est[+target.dataset.est]:visible[+target.dataset.bar];
    if(!b) return;
    if(estimated) tip.textContent=`假设估算 · ${b.side==='L'?'多头':'空头'} · ${b.t}x\n假设强平价 $${precise(b.px)}\n估算名义 $${money(b.notional)}\n不是真实仓位，不计入累计`;
    else{
      const far=b.side==='L'?b.px_low:b.px_high;
      const crosses=b.px_low<mark&&b.px_high>mark;
      tip.textContent=`${b.side==='L'?'多头':'空头'} · ${watch?'本机Watchlist':'公开聚合'}${legacy?' · 旧14档第'+(b.band+1)+'档':''}\n${legacy?'原桶极值区间':'固定价格桶'} $${precise(b.lo)} — $${precise(b.hi)}${legacy?'':'（右端不含）'}\n桶内强平价 $${precise(b.px_low)} — $${precise(b.px_high)}\n本桶名义 $${money(b.notional)} · ${b.positions} 仓\n从行情价至远端极值累计 $${money(cum.at(b.side,far))}\n${crosses?'跨现价桶：区间内金额不可定位；累计仅含可确定完整基础桶':b.side==='L'&&b.px_high>mark||b.side==='S'&&b.px_low<mark?'方向已越过现价：仍保留原桶，未认定已爆仓':'累计仅计同侧完整基础桶，含视窗外近端桶'}`;
    }
    tip.hidden=false;
    const r=frame.getBoundingClientRect(),tr=target.getBoundingClientRect();
    const px=event.clientX||tr.x+tr.width/2,py=event.clientY||tr.y;
    tip.style.left=Math.max(8,Math.min(r.width-350,px-r.left+14))+'px';
    tip.style.top=Math.max(8,Math.min(r.height-190,py-r.top-50))+'px';
  }
  svg.onpointermove=tooltip;svg.onmousemove=tooltip;svg.onmouseover=tooltip;svg.onfocusin=tooltip;svg.onpointerdown=tooltip;svg.onpointerleave=()=>tip.hidden=true;svg.onmouseleave=()=>tip.hidden=true;svg.onfocusout=()=>tip.hidden=true;
  svg.onkeydown=event=>{if(event.key==='Escape')tip.hidden=true;if(['ArrowLeft','ArrowRight'].includes(event.key)){const nodes=[...svg.querySelectorAll('[data-bar]')],i=nodes.indexOf(document.activeElement);nodes[Math.max(0,Math.min(nodes.length-1,i+(event.key==='ArrowRight'?1:-1)))]?.focus();event.preventDefault();}};
  if(!chartWired){
    chartWired=true;
    $('source').onchange=()=>drawChart();$('resolution').onchange=()=>drawChart();
    $('span').onchange=()=>{chartWindow=null;drawChart();};
    $('resetView').onclick=()=>{chartWindow=null;drawChart();};
    const zoom=scale=>{const center=(chartWindow[0]+chartWindow[1])/2,half=(chartWindow[1]-chartWindow[0])*scale/2;chartWindow=[Math.max(0,center-half),center+half];drawChart();};
    $('zoomIn').onclick=()=>zoom(.65);$('zoomOut').onclick=()=>zoom(1/.65);
    svg.addEventListener('wheel',event=>{event.preventDefault();zoom(event.deltaY>0?1.15:1/1.15);},{passive:false});
    $('applyRange').onclick=()=>{const lo=+$('priceMin').value,hi=+$('priceMax').value;if(Number.isFinite(lo)&&Number.isFinite(hi)&&lo>=0&&hi>lo){chartWindow=[lo,hi];drawChart();}else{$('chartNote').textContent='请输入有效价格区间：0 ≤ 下限 < 上限。';}};
  }
}
function precise(n){return Number(n).toLocaleString('en-US',{maximumSignificantDigits:10});}
function money(n){return Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}
function escapeChart(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
