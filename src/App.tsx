import { useMemo, useState } from 'react'
import { AlertCircle, ArrowDownToLine, ArrowRight, ArrowUpFromLine, Bike, CheckCircle2, ChevronDown, CircleAlert, Clock3, Database, MapPin, RefreshCw, Search, SlidersHorizontal, Truck, WifiOff } from 'lucide-react'
import { stationSeeds, timeOptions } from './data'
import type { DataHealth, RouteRecommendation, Station, Status } from './types'

const statusMeta: Record<Status, {label:string; icon:string}> = {
  shortage:{label:'부족',icon:'▼'}, normal:{label:'정상',icon:'●'}, surplus:{label:'과잉',icon:'▲'}
}

const pseudo = (seed:number) => Math.sin(seed * 999) * .5 + .5
const clamp = (n:number,min:number,max:number) => Math.max(min,Math.min(max,n))

function buildStations(hour:number, refreshTick:number): Station[] {
  const rush = hour === 8 ? 1 : hour === 18 ? -0.72 : hour === 22 ? .35 : .12
  const rows = stationSeeds.map((s,i) => {
    const noise = Math.round((pseudo(i + refreshTick * .37)-.5)*4)
    const current = clamp(s.base + noise + (hour===18 ? Math.round(s.bias*.25) : hour===13 ? 2 : 0), 0, s.capacity)
    const directional = s.bias * rush
    const rentals = clamp(Math.round(5 + Math.max(0,-directional) + pseudo(i+hour)*5),1,18)
    const returns = clamp(Math.round(5 + Math.max(0,directional) + pseudo(i*2+hour)*4),1,18)
    const expected = current + returns - rentals
    const low = Math.ceil(s.capacity*.2), high = Math.floor(s.capacity*.8), target = Math.round(s.capacity*.5)
    const status:Status = expected <= low ? 'shortage' : expected >= high ? 'surplus' : 'normal'
    const recommendation = status==='shortage' ? target-expected : status==='surplus' ? expected-target : 0
    const trend = Array.from({length:13},(_,j)=>clamp(Math.round(current+(j-12)*(rentals-returns)/12+(pseudo(i*15+j)-.5)*3),0,s.capacity))
    const forecast = Array.from({length:7},(_,j)=>Math.round(current+(expected-current)*j/6))
    const historicalAvg = Array.from({length:7},(_,j)=>clamp(Math.round(current+(returns-rentals)*j/8+2),0,s.capacity))
    const collectedAt = new Date(2026,9,1,hour,s.dataHealth==='delayed'?47:55)
    return {...s,current,rentals,returns,expected,recommendation,status,priority:0,collectedAt,history:trend,forecast,historicalAvg,dataHealth:s.dataHealth??'normal'}
  })
  return rows.sort((a,b)=>((b.status==='shortage'?2:b.status==='surplus'?1:0)*100+b.recommendation)-((a.status==='shortage'?2:a.status==='surplus'?1:0)*100+a.recommendation)).map((s,i)=>({...s,priority:i+1}))
}

function distance(a:Station,b:Station){
  const R=6371, dLat=(b.lat-a.lat)*Math.PI/180, dLon=(b.lng-a.lng)*Math.PI/180
  const x=Math.sin(dLat/2)**2+Math.cos(a.lat*Math.PI/180)*Math.cos(b.lat*Math.PI/180)*Math.sin(dLon/2)**2
  return R*2*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))
}

function buildRoutes(stations:Station[]):RouteRecommendation[]{
  const shortages=stations.filter(s=>s.status==='shortage').slice(0,6)
  const pool=stations.filter(s=>s.status==='surplus').map(s=>({...s,available:s.recommendation}))
  return shortages.flatMap(to=>{
    const source=pool.filter(s=>s.available>0).sort((a,b)=>distance(a,to)-distance(b,to))[0]
    if(!source)return []
    const quantity=Math.max(1,Math.min(to.recommendation,source.available,8)); source.available-=quantity
    return [{from:source,to,quantity,distance:distance(source,to),fromAfter:source.expected-quantity,toAfter:to.expected+quantity}]
  })
}

function Health({state}:{state:DataHealth}){
  if(state==='normal')return <span className="health ok"><CheckCircle2/> 정상 수집</span>
  if(state==='delayed')return <span className="health delayed"><Clock3/> 수집 지연</span>
  return <span className="health missing"><WifiOff/> 일부 누락</span>
}

function StatCard({icon,title,value,unit,tone,sub}:{icon:React.ReactNode,title:string,value:string|number,unit?:string,tone?:string,sub:string}){
  return <article className={`stat-card ${tone??''}`}><div className="stat-head"><span>{title}</span><i>{icon}</i></div><div className="stat-value">{value}<small>{unit}</small></div><p>{sub}</p></article>
}

function SeoulMap({stations,selected,onSelect}:{stations:Station[];selected:string;onSelect:(id:string)=>void}){
  const minLng=126.82,maxLng=127.16,minLat=37.46,maxLat=37.68
  const p=(s:Station)=>({x:40+(s.lng-minLng)/(maxLng-minLng)*620,y:390-(s.lat-minLat)/(maxLat-minLat)*340})
  return <div className="map-wrap">
    <svg viewBox="0 0 700 430" role="img" aria-label="서울 대여소 현황 지도">
      <path className="seoul-shape" d="M60 197 L91 133 151 121 181 70 252 57 302 89 359 54 421 91 486 81 527 116 627 131 651 194 621 245 650 299 580 344 491 338 430 376 363 351 296 387 246 344 172 351 127 310 74 287 91 238Z"/>
      <path className="river" d="M55 252 C135 206 189 285 267 245 S389 198 467 249 S582 280 657 232"/>
      <text x="110" y="115" className="map-label">은평 · 강북</text><text x="520" y="126" className="map-label">노원 · 강동</text>
      <text x="87" y="331" className="map-label">서남권</text><text x="510" y="343" className="map-label">동남권</text>
      {stations.map(s=>{const pt=p(s); return <g key={s.id} className={`marker ${s.status} ${selected===s.id?'selected':''}`} transform={`translate(${pt.x} ${pt.y})`} onClick={()=>onSelect(s.id)} role="button" tabIndex={0} onKeyDown={e=>e.key==='Enter'&&onSelect(s.id)}>
        <circle r={selected===s.id?12:9}/><circle className="pulse" r="16"/><text y="3">{statusMeta[s.status].icon}</text>
      </g>})}
    </svg>
    <div className="map-legend"><span><i className="shortage"/>▼ 부족</span><span><i className="surplus"/>▲ 과잉</span><span><i className="normal"/>● 정상</span></div>
  </div>
}

function TrendChart({station}:{station:Station}){
  const past=station.history, future=station.forecast, all=[...past,...future.slice(1)], max=Math.max(station.capacity,...all), W=600,H=175,pad=22
  const points=(arr:number[],start:number,total:number)=>arr.map((v,i)=>`${pad+(start+i)/(total-1)*(W-pad*2)},${H-pad-v/max*(H-pad*2)}`).join(' ')
  return <div className="chart"><svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
    {[.25,.5,.75].map(v=><line key={v} x1={pad} x2={W-pad} y1={H*v} y2={H*v} className="grid"/>)}
    <line x1={pad+12/(18)*(W-pad*2)} x2={pad+12/(18)*(W-pad*2)} y1={12} y2={H-pad} className="now-line"/>
    <polyline points={points(past,0,19)} className="past-line"/><polyline points={points(future,12,19)} className="future-line"/><polyline points={points(station.historicalAvg,12,19)} className="avg-line"/>
  </svg><div className="chart-axis"><span>-60분</span><span>-30분</span><b>현재</b><span>+15분</span><span>+30분</span></div></div>
}

export default function App(){
  const [hour,setHour]=useState(8),[tick,setTick]=useState(0),[selected,setSelected]=useState('ST-101')
  const [status,setStatus]=useState<'all'|Status>('all'),[district,setDistrict]=useState('all'),[query,setQuery]=useState('')
  const [sort,setSort]=useState<'priority'|'expected'>('priority'),[loading,setLoading]=useState(false)
  const stations=useMemo(()=>buildStations(hour,tick),[hour,tick])
  const selectedStation=stations.find(s=>s.id===selected)??stations[0]
  const districts=[...new Set(stations.map(s=>s.district))].sort()
  const filtered=stations.filter(s=>(status==='all'||s.status===status)&&(district==='all'||s.district===district)&&(`${s.name} ${s.id}`.toLowerCase().includes(query.toLowerCase()))).sort((a,b)=>sort==='priority'?a.priority-b.priority:a.expected-b.expected)
  const routes=buildRoutes(stations)
  const shortages=stations.filter(s=>s.status==='shortage'),surpluses=stations.filter(s=>s.status==='surplus')
  const totalMove=routes.reduce((n,r)=>n+r.quantity,0)
  const refresh=()=>{setLoading(true);setTimeout(()=>{setTick(t=>t+1);setLoading(false)},700)}
  const choose=(id:string)=>{setSelected(id);document.getElementById('detail')?.scrollIntoView({behavior:'smooth',block:'nearest'})}

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark"><Bike/></span><div><strong>따릉이 운영 관제</strong><small>수요 예측 · 재배치 지원</small></div></div><div className="top-actions"><span className="demo-badge"><Database/> DEMO DATA</span><label className="time-select"><Clock3/><select value={hour} onChange={e=>setHour(+e.target.value)}>{timeOptions.map(t=><option value={t.value} key={t.value}>{t.label}</option>)}</select><ChevronDown/></label><button className="refresh" onClick={refresh} disabled={loading}><RefreshCw className={loading?'spin':''}/>{loading?'갱신 중':'데이터 새로고침'}</button></div></header>
    <main>
      <div className="page-title"><div><p className="eyebrow">SEOUL BIKE OPERATIONS</p><h1>실시간 수요 예측 현황</h1><p>향후 30분 수요를 바탕으로 대여소별 재배치를 지원합니다.</p></div><div className="sync"><span className="live-dot"/> 마지막 수집 <b>2026.10.01 {String(hour).padStart(2,'0')}:55</b><small>모델 baseline-v1</small></div></div>
      <section className="stats-grid">
        <StatCard icon={<MapPin/>} title="전체 대여소" value={stations.length} unit="개소" sub="서울 14개 자치구"/>
        <StatCard icon={<ArrowDownToLine/>} title="부족 예상" value={shortages.length} unit="개소" tone="danger" sub="즉시 보충 검토"/>
        <StatCard icon={<ArrowUpFromLine/>} title="과잉 예상" value={surpluses.length} unit="개소" tone="blue" sub="수거 가능 대여소"/>
        <StatCard icon={<Truck/>} title="추천 재배치" value={totalMove} unit="대" tone="teal" sub={`${routes.length}개 이동 경로`}/>
      </section>

      <section className="top-grid">
        <article className="panel map-panel"><div className="panel-head"><div><h2>서울 대여소 현황</h2><p>마커를 선택하면 상세 현황을 확인할 수 있습니다.</p></div><span className="count">표시 {stations.length}개</span></div><SeoulMap stations={stations} selected={selected} onSelect={choose}/></article>
        <article className="panel selected-card"><div className="panel-head"><div><p className="eyebrow">SELECTED STATION</p><h2>{selectedStation.name}</h2><p>{selectedStation.district} · {selectedStation.id}</p></div><span className={`status-pill ${selectedStation.status}`}>{statusMeta[selectedStation.status].icon} {statusMeta[selectedStation.status].label}</span></div>
          <div className="stock-flow"><div><small>현재 재고</small><strong>{selectedStation.current}<em>대</em></strong></div><ArrowRight/><div><small>30분 후 예상</small><strong className={selectedStation.expected<0?'negative':''}>{selectedStation.expected}<em>대</em></strong></div></div>
          <div className="mini-grid"><div><ArrowUpFromLine/><span>예상 대여<strong>{selectedStation.rentals}대</strong></span></div><div><ArrowDownToLine/><span>예상 반납<strong>{selectedStation.returns}대</strong></span></div></div>
          <div className={`recommend ${selectedStation.status}`}><Truck/><div><small>운영 권장</small><strong>{selectedStation.status==='shortage'?`${selectedStation.recommendation}대 보충` : selectedStation.status==='surplus'?`${selectedStation.recommendation}대 수거`:'재배치 불필요'}</strong></div></div>
          <Health state={selectedStation.dataHealth??'normal'}/>
        </article>
      </section>

      <section className="panel table-panel"><div className="panel-head"><div><h2>재배치 우선순위</h2><p>예측 재고와 운영 임계치에 따라 자동 산정됩니다.</p></div><span className="count">{filtered.length}개 결과</span></div>
        <div className="filters"><label className="search"><Search/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="대여소명 또는 ID 검색"/></label><select value={status} onChange={e=>setStatus(e.target.value as typeof status)}><option value="all">전체 상태</option><option value="shortage">▼ 부족</option><option value="surplus">▲ 과잉</option><option value="normal">● 정상</option></select><select value={district} onChange={e=>setDistrict(e.target.value)}><option value="all">전체 지역</option>{districts.map(d=><option key={d}>{d}</option>)}</select><label className="sort"><SlidersHorizontal/><select value={sort} onChange={e=>setSort(e.target.value as typeof sort)}><option value="priority">우선순위순</option><option value="expected">예상 재고 낮은순</option></select></label></div>
        <div className="table-scroll"><table><thead><tr><th>순위</th><th>대여소</th><th>현재 재고</th><th>예상 대여</th><th>예상 반납</th><th>30분 후</th><th>권장 수량</th><th>상태</th><th>수집 시각</th></tr></thead><tbody>{filtered.map(s=><tr key={s.id} className={selected===s.id?'active':''} onClick={()=>choose(s.id)}><td><b className="rank">{s.priority}</b></td><td><strong>{s.name}</strong><small>{s.district} · {s.id}</small></td><td>{s.current}<small> / {s.capacity}</small></td><td>{s.rentals}대</td><td>{s.returns}대</td><td><b className={s.expected<0?'negative':''}>{s.expected}대</b></td><td>{s.recommendation? <b>{s.recommendation}대 {s.status==='shortage'?'보충':'수거'}</b>:'—'}</td><td><span className={`status-pill ${s.status}`}>{statusMeta[s.status].icon} {statusMeta[s.status].label}</span></td><td><span className="time-cell">{s.dataHealth==='delayed'?<CircleAlert/>:s.dataHealth==='missing'?<WifiOff/>:<CheckCircle2/>}{String(s.collectedAt.getHours()).padStart(2,'0')}:{String(s.collectedAt.getMinutes()).padStart(2,'0')}</span></td></tr>)}</tbody></table>{filtered.length===0&&<div className="empty"><Search/><h3>조건에 맞는 대여소가 없습니다</h3><p>검색어 또는 필터를 변경해 주세요.</p><button onClick={()=>{setQuery('');setStatus('all');setDistrict('all')}}>필터 초기화</button></div>}</div>
      </section>

      <section className="bottom-grid" id="detail">
        <article className="panel detail-panel"><div className="panel-head"><div><p className="eyebrow">STATION DETAIL</p><h2>{selectedStation.name} 재고 추이</h2><p>최근 1시간 실제값과 향후 30분 예측</p></div><Health state={selectedStation.dataHealth??'normal'}/></div><TrendChart station={selectedStation}/><div className="chart-legend"><span><i className="past"/>실제 재고</span><span><i className="future"/>예측 재고</span><span><i className="average"/>과거 평균</span></div><div className="detail-metrics"><div><small>동시간대 과거 평균</small><strong>{selectedStation.historicalAvg.at(-1)}대</strong></div><div><small>현재 거치율</small><strong>{Math.round(selectedStation.current/selectedStation.capacity*100)}%</strong></div><div><small>30분 후 거치율</small><strong>{Math.round(selectedStation.expected/selectedStation.capacity*100)}%</strong></div></div>
          <div className="nearby"><h3>인접 운영 후보</h3>{stations.filter(s=>s.id!==selectedStation.id&&s.status!==selectedStation.status).sort((a,b)=>distance(a,selectedStation)-distance(b,selectedStation)).slice(0,3).map(s=><button key={s.id} onClick={()=>choose(s.id)}><span className={`dot ${s.status}`}/><span><b>{s.name}</b><small>{distance(s,selectedStation).toFixed(1)}km · 예상 {s.expected}대</small></span><ArrowRight/></button>)}</div>
        </article>
        <article className="panel routes-panel"><div className="panel-head"><div><h2>추천 재배치 경로</h2><p>거리와 가용 수량을 함께 고려했습니다.</p></div><span className="count">{routes.length}건</span></div><div className="route-list">{routes.map((r,i)=><div className="route-card" key={r.to.id}><div className="route-num">{i+1}</div><div className="route-main"><div className="route-stations"><span><small>출발 · 수거</small><b>{r.from.name}</b><em>예상 {r.from.expected} → {r.fromAfter}대</em></span><span className="route-arrow"><strong>{r.quantity}대</strong><ArrowRight/></span><span><small>도착 · 보충</small><b>{r.to.name}</b><em>예상 {r.to.expected} → {r.toAfter}대</em></span></div><div className="route-foot"><span><MapPin/> 직선거리 {r.distance.toFixed(1)}km</span><span><Clock3/> 약 {Math.max(5,Math.round(r.distance*4))}분</span></div></div></div>)}</div></article>
      </section>
    </main>
    {loading&&<div className="loading-overlay"><div><RefreshCw className="spin"/><b>최신 데이터를 불러오는 중입니다</b><span>5분 주기 수집을 시뮬레이션합니다.</span></div></div>}
    <footer><AlertCircle/> 본 화면의 모든 정보는 프로토타입용 더미데이터이며 실제 운영 판단에 사용할 수 없습니다.</footer>
  </div>
}
