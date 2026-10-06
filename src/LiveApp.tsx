import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Bike, CheckCircle2, Clock3, Database, MapPin, RefreshCw, Search, SlidersHorizontal, WifiOff } from 'lucide-react'
import { fetchInventory, fetchStationHistory, type InventoryPoint, type InventoryStatus, type LiveStation } from './api'
import type { Status } from './types'

const statusMeta: Record<Status, { label: string; icon: string }> = {
  shortage: { label: '재고 낮음', icon: '▼' }, normal: { label: '보통', icon: '●' }, surplus: { label: '재고 많음', icon: '▲' },
}
const stationStatus = (s: LiveStation): Status => s.currentBikes === 0 || (s.capacity > 0 && s.occupancyRate <= 20) ? 'shortage' : s.capacity > 0 && s.occupancyRate >= 80 ? 'surplus' : 'normal'
const kst = (value?: string) => value ? new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value)) : '—'
function distance(a: LiveStation, b: LiveStation) {
  const R=6371,dLat=(b.latitude-a.latitude)*Math.PI/180,dLon=(b.longitude-a.longitude)*Math.PI/180
  const x=Math.sin(dLat/2)**2+Math.cos(a.latitude*Math.PI/180)*Math.cos(b.latitude*Math.PI/180)*Math.sin(dLon/2)**2
  return R*2*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))
}
function StatCard({title,value,unit,sub,tone='',icon}:{title:string;value:string|number;unit?:string;sub:string;tone?:string;icon:React.ReactNode}) {
  return <article className={`stat-card ${tone}`}><div className="stat-head"><span>{title}</span><i>{icon}</i></div><div className="stat-value">{value}<small>{unit}</small></div><p>{sub}</p></article>
}
function SeoulMap({stations,selected,onSelect}:{stations:LiveStation[];selected:string;onSelect:(id:string)=>void}) {
  const p=(s:LiveStation)=>({x:40+(s.longitude-126.76)/(127.20-126.76)*620,y:390-(s.latitude-37.42)/(37.71-37.42)*340})
  return <div className="map-wrap"><svg viewBox="0 0 700 430" role="img" aria-label="서울 실시간 대여소 재고 지도">
    <path className="seoul-shape" d="M60 197 L91 133 151 121 181 70 252 57 302 89 359 54 421 91 486 81 527 116 627 131 651 194 621 245 650 299 580 344 491 338 430 376 363 351 296 387 246 344 172 351 127 310 74 287 91 238Z"/>
    <path className="river" d="M55 252 C135 206 189 285 267 245 S389 198 467 249 S582 280 657 232"/>
    {stations.map(s=>{const pt=p(s),state=stationStatus(s),active=selected===s.stationId;return <g key={s.stationId} className={`marker ${state} ${active?'selected':''}`} transform={`translate(${pt.x} ${pt.y})`} onClick={()=>onSelect(s.stationId)} role="button" tabIndex={0} onKeyDown={e=>e.key==='Enter'&&onSelect(s.stationId)}><circle r={active?7:2.5}/>{active&&<circle className="pulse" r="12"/>}</g>})}
  </svg><div className="map-legend"><span><i className="shortage"/>▼ 재고 낮음</span><span><i className="surplus"/>▲ 재고 많음</span><span><i className="normal"/>● 보통</span></div></div>
}
function HistoryChart({points,capacity}:{points:InventoryPoint[];capacity:number}) {
  if(points.length<2)return <div className="empty compact"><Clock3/><h3>재고 이력을 수집 중입니다</h3><p>두 번 이상 정상 수집되면 실제 추이가 표시됩니다.</p></div>
  const W=600,H=175,pad=22,max=Math.max(capacity,...points.map(p=>p.currentBikes),1)
  const coords=points.map((p,i)=>`${pad+i/(points.length-1)*(W-pad*2)},${H-pad-p.currentBikes/max*(H-pad*2)}`).join(' ')
  return <div className="chart"><svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">{[.25,.5,.75].map(v=><line key={v} x1={pad} x2={W-pad} y1={H*v} y2={H*v} className="grid"/>)}<polyline points={coords} className="past-line"/></svg><div className="chart-axis"><span>{kst(points[0].slot)}</span><b>실제 수집 재고</b><span>{kst(points.at(-1)?.slot)}</span></div></div>
}

export default function LiveApp(){
  const [stations,setStations]=useState<LiveStation[]>([]),[runStatus,setRunStatus]=useState<InventoryStatus|null>(null),[selected,setSelected]=useState(''),[history,setHistory]=useState<InventoryPoint[]>([])
  const [filter,setFilter]=useState<'all'|Status>('all'),[query,setQuery]=useState(''),[sort,setSort]=useState<'name'|'bikes'|'rate'>('name'),[page,setPage]=useState(1)
  const [loading,setLoading]=useState(true),[error,setError]=useState('')
  const load=async()=>{setLoading(true);setError('');try{const result=await fetchInventory();setStations(result.stations);setRunStatus(result.status);setSelected(current=>result.stations.some(s=>s.stationId===current)?current:result.stations[0]?.stationId??'')}catch(reason){setError(reason instanceof Error?reason.message:'데이터를 불러오지 못했습니다.')}finally{setLoading(false)}}
  useEffect(()=>{void load()},[])
  useEffect(()=>{if(!selected)return;const controller=new AbortController();fetchStationHistory(selected,controller.signal).then(setHistory).catch(reason=>{if((reason as Error).name!=='AbortError')setHistory([])});return()=>controller.abort()},[selected,runStatus?.runId])
  const filtered=useMemo(()=>{const result=stations.filter(s=>(filter==='all'||stationStatus(s)===filter)&&`${s.stationName} ${s.stationId}`.toLowerCase().includes(query.toLowerCase()));result.sort((a,b)=>sort==='bikes'?a.currentBikes-b.currentBikes:sort==='rate'?a.occupancyRate-b.occupancyRate:a.stationName.localeCompare(b.stationName,'ko'));return result},[stations,filter,query,sort])
  useEffect(()=>setPage(1),[filter,query,sort])
  const pageSize=50,pageCount=Math.max(1,Math.ceil(filtered.length/pageSize)),rows=filtered.slice((page-1)*pageSize,page*pageSize),current=stations.find(s=>s.stationId===selected)
  const emptyCount=stations.filter(s=>s.currentBikes===0).length,highCount=stations.filter(s=>stationStatus(s)==='surplus').length,totalBikes=stations.reduce((n,s)=>n+s.currentBikes,0)
  const nearby=current?stations.filter(s=>s.stationId!==current.stationId).sort((a,b)=>distance(a,current)-distance(b,current)).slice(0,3):[]
  if(error&&stations.length===0)return <div className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark"><Bike/></span><div><strong>따릉이 운영 관제</strong><small>실시간 재고 현황</small></div></div></header><main><section className="panel empty error-state"><WifiOff/><h2>백엔드에 연결할 수 없습니다</h2><p>{error}</p><button onClick={()=>void load()}>다시 시도</button></section></main></div>
  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark"><Bike/></span><div><strong>따릉이 운영 관제</strong><small>실시간 재고 현황</small></div></div><div className="top-actions"><span className="demo-badge live"><Database/> LIVE SQLITE</span><button className="refresh" onClick={()=>void load()} disabled={loading}><RefreshCw className={loading?'spin':''}/>{loading?'조회 중':'최신 DB 조회'}</button></div></header>
    <main>
      <div className="page-title"><div><p className="eyebrow">SEOUL BIKE INVENTORY</p><h1>실시간 대여소 재고 현황</h1><p>마지막으로 전체 수집에 성공한 서울시 API 데이터를 표시합니다.</p></div><div className="sync"><span className="live-dot"/> 마지막 성공 슬롯 <b>{kst(runStatus?.slot)}</b><small>예측 모델 연결 전</small></div></div>
      {error&&<div className="inline-alert"><AlertCircle/>{error} · 이전 정상 데이터를 표시합니다.</div>}
      <section className="stats-grid"><StatCard icon={<MapPin/>} title="전체 대여소" value={stations.length.toLocaleString()} unit="개소" sub="마지막 정상 수집 기준"/><StatCard icon={<Bike/>} title="대여 가능 자전거" value={totalBikes.toLocaleString()} unit="대" tone="teal" sub="전체 대여소 합계"/><StatCard icon={<AlertCircle/>} title="재고 0대" value={emptyCount.toLocaleString()} unit="개소" tone="danger" sub="현재 대여 불가"/><StatCard icon={<CheckCircle2/>} title="거치율 80% 이상" value={highCount.toLocaleString()} unit="개소" tone="blue" sub="현재 재고가 많은 곳"/></section>
      <section className="top-grid"><article className="panel map-panel"><div className="panel-head"><div><h2>서울 대여소 현황</h2><p>실제 좌표와 현재 재고 수준을 표시합니다.</p></div><span className="count">표시 {stations.length.toLocaleString()}개</span></div><SeoulMap stations={stations} selected={selected} onSelect={setSelected}/></article>
        <article className="panel selected-card">{current?<><div className="panel-head"><div><p className="eyebrow">SELECTED STATION</p><h2>{current.stationName}</h2><p>{current.stationId}</p></div><span className={`status-pill ${stationStatus(current)}`}>{statusMeta[stationStatus(current)].icon} {statusMeta[stationStatus(current)].label}</span></div><div className="stock-flow single"><div><small>현재 대여 가능</small><strong>{current.currentBikes}<em>대</em></strong></div></div><div className="mini-grid"><div><Bike/><span>거치대 수<strong>{current.capacity}개</strong></span></div><div><Database/><span>원본 거치율<strong>{current.occupancyRate.toFixed(0)}%</strong></span></div></div><div className="recommend normal"><Clock3/><div><small>수집 수신 시각</small><strong>{kst(current.fetchedAt)}</strong></div></div><span className={`health ${runStatus?.dataQuality==='normal'?'ok':'delayed'}`}>{runStatus?.dataQuality==='normal'?<CheckCircle2/>:<Clock3/>}{runStatus?.dataQuality==='normal'?'정상 수집':'10분 이상 지연'}</span></>:<div className="empty"><Search/><h3>대여소를 선택해 주세요</h3></div>}</article>
      </section>
      <section className="panel table-panel"><div className="panel-head"><div><h2>실시간 대여소 목록</h2><p>현재 재고 기준 상태이며 수요 예측 결과가 아닙니다.</p></div><span className="count">{filtered.length.toLocaleString()}개 결과</span></div><div className="filters"><label className="search"><Search/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="대여소명 또는 ID 검색"/></label><select value={filter} onChange={e=>setFilter(e.target.value as typeof filter)}><option value="all">전체 상태</option><option value="shortage">▼ 재고 낮음</option><option value="surplus">▲ 재고 많음</option><option value="normal">● 보통</option></select><label className="sort"><SlidersHorizontal/><select value={sort} onChange={e=>setSort(e.target.value as typeof sort)}><option value="name">대여소명순</option><option value="bikes">재고 낮은순</option><option value="rate">거치율 낮은순</option></select></label></div>
        <div className="table-scroll"><table><thead><tr><th>#</th><th>대여소</th><th>거치대 수</th><th>현재 재고</th><th>거치율</th><th>상태</th><th>수집 수신 시각</th></tr></thead><tbody>{rows.map((s,i)=>{const state=stationStatus(s);return <tr key={s.stationId} className={selected===s.stationId?'active':''} onClick={()=>setSelected(s.stationId)}><td><b className="rank">{(page-1)*pageSize+i+1}</b></td><td><strong>{s.stationName}</strong><small>{s.stationId}</small></td><td>{s.capacity}개</td><td><b>{s.currentBikes}대</b></td><td>{s.occupancyRate.toFixed(0)}%</td><td><span className={`status-pill ${state}`}>{statusMeta[state].icon} {statusMeta[state].label}</span></td><td><span className="time-cell"><CheckCircle2/>{kst(s.fetchedAt)}</span></td></tr>})}</tbody></table>{filtered.length===0&&<div className="empty"><Search/><h3>조건에 맞는 대여소가 없습니다</h3><p>검색어나 필터를 변경해 주세요.</p><button onClick={()=>{setQuery('');setFilter('all')}}>필터 초기화</button></div>}</div>
        {filtered.length>0&&<div className="pagination"><button disabled={page===1} onClick={()=>setPage(v=>v-1)}>이전</button><span>{page} / {pageCount}</span><button disabled={page===pageCount} onClick={()=>setPage(v=>v+1)}>다음</button></div>}
      </section>
      {current&&<section className="bottom-grid" id="detail"><article className="panel detail-panel"><div className="panel-head"><div><p className="eyebrow">ACTUAL INVENTORY</p><h2>{current.stationName} 실제 재고 추이</h2><p>정상 완료된 최근 수집 결과만 사용합니다.</p></div><span className="count">{history.length}개 시점</span></div><HistoryChart points={history} capacity={current.capacity}/><div className="detail-metrics"><div><small>현재 재고</small><strong>{current.currentBikes}대</strong></div><div><small>거치대 수</small><strong>{current.capacity}개</strong></div><div><small>원본 거치율</small><strong>{current.occupancyRate.toFixed(0)}%</strong></div></div><div className="nearby"><h3>가까운 대여소</h3>{nearby.map(s=><button key={s.stationId} onClick={()=>setSelected(s.stationId)}><span className={`dot ${stationStatus(s)}`}/><span><b>{s.stationName}</b><small>{distance(s,current).toFixed(2)}km · 현재 {s.currentBikes}대</small></span><MapPin/></button>)}</div></article><article className="panel routes-panel"><div className="panel-head"><div><h2>수요 예측·재배치 추천</h2><p>다음 구현 단계입니다.</p></div><span className="count">MODEL PENDING</span></div><div className="empty model-pending"><SlidersHorizontal/><h3>예측 모델 연결 전</h3><p>현재 화면은 실시간 재고만 표시합니다. 과거 대여·반납 데이터를 확보한 뒤 30분 예측과 재배치 추천을 연결합니다.</p></div></article></section>}
    </main>
    {loading&&<div className="loading-overlay"><div><RefreshCw className="spin"/><b>SQLite의 최신 재고를 조회하는 중입니다</b><span>외부 서울시 API를 새로 호출하지 않습니다.</span></div></div>}
    <footer><AlertCircle/> 서울시 실시간 대여정보를 수집한 데이터입니다. 원본 관측 시각이 없어 시스템 수신 시각을 표시합니다.</footer>
  </div>
}
