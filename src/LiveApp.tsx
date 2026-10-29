import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, ArrowDownToLine, ArrowRight, ArrowUpFromLine, Bike, CheckCircle2, Clock3, Database, MapPin, RefreshCw, Search, SlidersHorizontal, Truck, WifiOff } from 'lucide-react'
import { fetchInventory, fetchStationHistory, type InventoryPoint, type InventoryStatus, type LiveStation } from './api'
import type { Status } from './types'
import { LeafletStationMap } from './LeafletStationMap'

const statusMeta: Record<Status, { label: string; icon: string }> = {
  shortage: { label: '부족 예상', icon: '▼' },
  normal: { label: '정상 예상', icon: '●' },
  surplus: { label: '과잉 예상', icon: '▲' },
}

const stationStatus = (station: LiveStation): Status => {
  if (station.predictionAvailable && station.forecastStatus) return station.forecastStatus
  if (station.currentBikes === 0 || (station.capacity > 0 && station.occupancyRate <= 20)) return 'shortage'
  if (station.capacity > 0 && station.occupancyRate >= 80) return 'surplus'
  return 'normal'
}
const kst = (value?: string | null) => value ? new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value)) : '—'
const amount = (value: number | null) => value === null ? '—' : value.toFixed(1)

function distance(a: LiveStation, b: LiveStation) {
  const R=6371,dLat=(b.latitude-a.latitude)*Math.PI/180,dLon=(b.longitude-a.longitude)*Math.PI/180
  const x=Math.sin(dLat/2)**2+Math.cos(a.latitude*Math.PI/180)*Math.cos(b.latitude*Math.PI/180)*Math.sin(dLon/2)**2
  return R*2*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))
}

function StatCard({title,value,unit,sub,tone='',icon}:{title:string;value:string|number;unit?:string;sub:string;tone?:string;icon:React.ReactNode}) {
  return <article className={`stat-card ${tone}`}><div className="stat-head"><span>{title}</span><i>{icon}</i></div><div className="stat-value">{value}<small>{unit}</small></div><p>{sub}</p></article>
}

function InventoryForecastChart({points,capacity,expected}:{points:InventoryPoint[];capacity:number;expected:number|null}) {
  if(points.length<2)return <div className="empty compact"><Clock3/><h3>재고 이력을 수집 중입니다</h3><p>두 번 이상 정상 수집되면 실제 추이가 표시됩니다.</p></div>
  const W=600,H=175,pad=22,total=18
  const max=Math.max(capacity,...points.map(point=>point.currentBikes),expected??0,1)
  const xy=(index:number,value:number)=>`${pad+index/total*(W-pad*2)},${H-pad-value/max*(H-pad*2)}`
  const actual=points.map((point,index)=>xy(index+12-(points.length-1),point.currentBikes)).join(' ')
  const projected=expected===null?'':`${xy(12,points.at(-1)?.currentBikes??0)} ${xy(18,expected)}`
  return <div className="chart"><svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
    {[.25,.5,.75].map(value=><line key={value} x1={pad} x2={W-pad} y1={H*value} y2={H*value} className="grid"/>)}
    <line x1={pad+12/total*(W-pad*2)} x2={pad+12/total*(W-pad*2)} y1={12} y2={H-pad} className="now-line"/>
    <polyline points={actual} className="past-line"/>{projected&&<polyline points={projected} className="future-line"/>}
  </svg><div className="chart-axis"><span>-60분</span><span>-30분</span><b>현재</b><span>+15분</span><span>+30분</span></div></div>
}

export default function LiveApp(){
  const [stations,setStations]=useState<LiveStation[]>([]),[runStatus,setRunStatus]=useState<InventoryStatus|null>(null),[selected,setSelected]=useState(''),[history,setHistory]=useState<InventoryPoint[]>([])
  const [filter,setFilter]=useState<'all'|Status>('all'),[query,setQuery]=useState(''),[sort,setSort]=useState<'priority'|'expected'|'name'>('priority'),[page,setPage]=useState(1)
  const [loading,setLoading]=useState(true),[error,setError]=useState('')
  const load=async()=>{setLoading(true);setError('');try{const result=await fetchInventory();setStations(result.stations);setRunStatus(result.status);const predicted=result.stations.filter(station=>station.predictionAvailable);setSelected(current=>predicted.some(station=>station.stationId===current)?current:predicted[0]?.stationId??result.stations[0]?.stationId??'')}catch(reason){setError(reason instanceof Error?reason.message:'데이터를 불러오지 못했습니다.')}finally{setLoading(false)}}
  useEffect(()=>{void load()},[])
  useEffect(()=>{if(!selected)return;const controller=new AbortController();fetchStationHistory(selected,controller.signal).then(setHistory).catch(reason=>{if((reason as Error).name!=='AbortError')setHistory([])});return()=>controller.abort()},[selected,runStatus?.runId])

  const modeled=useMemo(()=>stations.filter(station=>station.predictionAvailable),[stations])
  const displayStations=modeled.length?modeled:stations
  const filtered=useMemo(()=>{const result=displayStations.filter(station=>(filter==='all'||stationStatus(station)===filter)&&`${station.stationName} ${station.stationId}`.toLowerCase().includes(query.toLowerCase()));result.sort((a,b)=>sort==='expected'?(a.expectedBikes30m??a.currentBikes)-(b.expectedBikes30m??b.currentBikes):sort==='priority'?(a.priority??9999)-(b.priority??9999):a.stationName.localeCompare(b.stationName,'ko'));return result},[displayStations,filter,query,sort])
  useEffect(()=>setPage(1),[filter,query,sort])
  const pageSize=50,pageCount=Math.max(1,Math.ceil(filtered.length/pageSize)),rows=filtered.slice((page-1)*pageSize,page*pageSize),current=displayStations.find(station=>station.stationId===selected)
  const shortages=displayStations.filter(station=>stationStatus(station)==='shortage'),surpluses=displayStations.filter(station=>stationStatus(station)==='surplus')
  const totalRecommended=shortages.reduce((total,station)=>total+station.recommendedQuantity,0)
  const nearbyCandidates=current?displayStations.filter(station=>station.stationId!==current.stationId&&stationStatus(station)===(stationStatus(current)==='shortage'?'surplus':'shortage')).sort((a,b)=>distance(a,current)-distance(b,current)).slice(0,4):[]

  if(error&&stations.length===0)return <div className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark"><Bike/></span><div><strong>따릉이 운영 관제</strong><small>수요 예측 · 재배치 지원</small></div></div></header><main><section className="panel empty error-state"><WifiOff/><h2>백엔드에 연결할 수 없습니다</h2><p>{error}</p><button onClick={()=>void load()}>다시 시도</button></section></main></div>
  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark"><Bike/></span><div><strong>따릉이 운영 관제</strong><small>강남구 30분 수요 예측</small></div></div><div className="top-actions"><span className="demo-badge live"><Database/> LIVE + MODEL</span><button className="refresh" onClick={()=>void load()} disabled={loading}><RefreshCw className={loading?'spin':''}/>{loading?'조회 중':'재고·예측 새로고침'}</button></div></header>
    <main>
      <div className="page-title"><div><p className="eyebrow">GANGNAM BIKE OPERATIONS</p><h1>30분 후 예상 재고 현황</h1><p>실시간 재고와 같은 요일·5분 시간대의 과거 평균 대여·반납량을 결합합니다.</p></div><div className="sync"><span className="live-dot"/> 기준 시각 <b>{kst(runStatus?.slot)}</b><small>모델 {runStatus?.predictionModel?.modelVersion??'연결 안 됨'}</small></div></div>
      {error&&<div className="inline-alert"><AlertCircle/>{error} · 이전 정상 데이터를 표시합니다.</div>}
      {!loading&&modeled.length===0&&<div className="inline-alert"><AlertCircle/>예측 DB를 찾지 못해 현재 재고 상태만 표시합니다. data/gangnam/gangnam.sqlite3를 확인해 주세요.</div>}
      <section className="stats-grid"><StatCard icon={<MapPin/>} title="예측 대상 대여소" value={modeled.length.toLocaleString()} unit="개소" sub="강남구·모델 ID 일치 기준"/><StatCard icon={<ArrowDownToLine/>} title="부족 예상" value={shortages.length.toLocaleString()} unit="개소" tone="danger" sub="30분 후 20% 이하"/><StatCard icon={<ArrowUpFromLine/>} title="과잉 예상" value={surpluses.length.toLocaleString()} unit="개소" tone="blue" sub="30분 후 80% 이상"/><StatCard icon={<Truck/>} title="권장 보충량" value={totalRecommended.toLocaleString()} unit="대" tone="teal" sub="목표 재고 50% 기준"/></section>
      <section className="top-grid"><article className="panel map-panel"><div className="panel-head"><div><h2>강남구 예측 대여소</h2><p>마커 색상은 현재 재고가 아니라 30분 후 예상 상태입니다.</p></div><span className="count">표시 {filtered.length.toLocaleString()}개</span></div><LeafletStationMap stations={filtered} selected={selected} onSelect={setSelected}/></article>
        <article className="panel selected-card">{current?<><div className="panel-head"><div><p className="eyebrow">SELECTED STATION</p><h2>{current.stationName}</h2><p>{current.district??'모델 범위 외'} · {current.stationId}</p></div><span className={`status-pill ${stationStatus(current)}`}>{statusMeta[stationStatus(current)].icon} {statusMeta[stationStatus(current)].label}</span></div><div className="stock-flow"><div><small>현재 재고</small><strong>{current.currentBikes}<em>대</em></strong></div><ArrowRight/><div><small>30분 후 예상</small><strong className={(current.expectedBikes30m??0)<0?'negative':''}>{amount(current.expectedBikes30m)}<em>대</em></strong></div></div><div className="mini-grid"><div><ArrowUpFromLine/><span>예상 대여<strong>{amount(current.expectedRentals30m)}대</strong></span></div><div><ArrowDownToLine/><span>예상 반납<strong>{amount(current.expectedReturns30m)}대</strong></span></div></div><div className={`recommend ${stationStatus(current)}`}><Truck/><div><small>운영 권장</small><strong>{current.recommendedAction==='replenish'?`${current.recommendedQuantity}대 보충`:current.recommendedAction==='collect'?`${current.recommendedQuantity}대 수거`:'재배치 불필요'}</strong></div></div><span className={`health ${runStatus?.dataQuality==='normal'?'ok':'delayed'}`}>{runStatus?.dataQuality==='normal'?<CheckCircle2/>:<Clock3/>}{runStatus?.dataQuality==='normal'?'정상 수집':'10분 이상 지연'}</span></>:<div className="empty"><Search/><h3>대여소를 선택해 주세요</h3></div>}</article>
      </section>
      <section className="panel table-panel"><div className="panel-head"><div><h2>재배치 우선순위</h2><p>예상 재고와 거치대 대비 임계치에 따라 산정됩니다.</p></div><span className="count">{filtered.length.toLocaleString()}개 결과</span></div><div className="filters"><label className="search"><Search/><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="대여소명 또는 ID 검색"/></label><select value={filter} onChange={event=>setFilter(event.target.value as typeof filter)}><option value="all">전체 상태</option><option value="shortage">▼ 부족 예상</option><option value="surplus">▲ 과잉 예상</option><option value="normal">● 정상 예상</option></select><label className="sort"><SlidersHorizontal/><select value={sort} onChange={event=>setSort(event.target.value as typeof sort)}><option value="priority">우선순위순</option><option value="expected">예상 재고 낮은순</option><option value="name">대여소명순</option></select></label></div>
        <div className="table-scroll"><table><thead><tr><th>순위</th><th>대여소</th><th>현재 재고</th><th>예상 대여</th><th>예상 반납</th><th>30분 후</th><th>권장 수량</th><th>상태</th><th>수집 시각</th></tr></thead><tbody>{rows.map(station=>{const state=stationStatus(station);return <tr key={station.stationId} className={selected===station.stationId?'active':''} onClick={()=>setSelected(station.stationId)}><td><b className="rank">{station.priority??'—'}</b></td><td><strong>{station.stationName}</strong><small>{station.district} · {station.stationId}</small></td><td>{station.currentBikes}<small> / {station.capacity}</small></td><td>{amount(station.expectedRentals30m)}대</td><td>{amount(station.expectedReturns30m)}대</td><td><b className={(station.expectedBikes30m??0)<0?'negative':''}>{amount(station.expectedBikes30m)}대</b></td><td>{station.recommendedQuantity?<b>{station.recommendedQuantity}대 {station.recommendedAction==='replenish'?'보충':'수거'}</b>:'—'}</td><td><span className={`status-pill ${state}`}>{statusMeta[state].icon} {statusMeta[state].label}</span></td><td><span className="time-cell"><CheckCircle2/>{kst(station.fetchedAt)}</span></td></tr>})}</tbody></table>{filtered.length===0&&<div className="empty"><Search/><h3>조건에 맞는 대여소가 없습니다</h3><p>검색어나 필터를 변경해 주세요.</p><button onClick={()=>{setQuery('');setFilter('all')}}>필터 초기화</button></div>}</div>
        {filtered.length>0&&<div className="pagination"><button disabled={page===1} onClick={()=>setPage(value=>value-1)}>이전</button><span>{page} / {pageCount}</span><button disabled={page===pageCount} onClick={()=>setPage(value=>value+1)}>다음</button></div>}
      </section>
      {current&&<section className="bottom-grid" id="detail"><article className="panel detail-panel"><div className="panel-head"><div><p className="eyebrow">INVENTORY FORECAST</p><h2>{current.stationName} 재고 추이</h2><p>최근 실제 재고와 과거 평균 기반 30분 예측</p></div><span className="count">{current.modelVersion??'MODEL N/A'}</span></div><InventoryForecastChart points={history} capacity={current.capacity} expected={current.expectedBikes30m}/><div className="chart-legend"><span><i/>실제 재고</span><span><i className="future"/>30분 예측</span></div><div className="detail-metrics"><div><small>예상 대여</small><strong>{amount(current.expectedRentals30m)}대</strong></div><div><small>예상 반납</small><strong>{amount(current.expectedReturns30m)}대</strong></div><div><small>추천 재배치</small><strong>{current.recommendedQuantity}대</strong></div></div></article><article className="panel routes-panel"><div className="panel-head"><div><h2>인접 재배치 후보</h2><p>{stationStatus(current)==='shortage'?'가까운 과잉 예상 대여소':'가까운 부족 예상 대여소'}</p></div><span className="count">{nearbyCandidates.length}개 후보</span></div><div className="route-list">{nearbyCandidates.map((station,index)=><button className="candidate-card" key={station.stationId} onClick={()=>setSelected(station.stationId)}><span className="route-num">{index+1}</span><span><b>{station.stationName}</b><small>{distance(station,current).toFixed(2)}km · 30분 후 {amount(station.expectedBikes30m)}대</small></span><span className={`status-pill ${stationStatus(station)}`}>{station.recommendedQuantity}대 {station.recommendedAction==='collect'?'수거':'보충'}</span><MapPin/></button>)}{nearbyCandidates.length===0&&<div className="empty compact"><Truck/><h3>연결 가능한 반대 상태 대여소가 없습니다</h3><p>정상 상태 대여소는 재배치 후보에서 제외합니다.</p></div>}</div></article></section>}
    </main>
    {loading&&<div className="loading-overlay"><div><RefreshCw className="spin"/><b>실시간 재고와 30분 예측을 결합하는 중입니다</b><span>SQLite의 최신 수집 결과와 seasonal-mean-v1을 조회합니다.</span></div></div>}
    <footer><AlertCircle/> 30분 예측은 같은 대여소·요일·5분 시간대의 과거 평균입니다. 날씨와 특수 이벤트는 아직 반영하지 않습니다.</footer>
  </div>
}
