import { useEffect, useRef } from 'react'
import L, { type CircleMarker, type LayerGroup, type Map as LeafletMap } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { LiveStation } from './api'
import type { Status } from './types'

type Props = {
  stations: LiveStation[]
  selected: string
  onSelect: (stationId: string) => void
}

type MarkerRecord = {
  marker: CircleMarker
  station: LiveStation
}

function stationStatus(station: LiveStation): Status {
  if (station.currentBikes === 0 || (station.capacity > 0 && station.occupancyRate <= 20)) return 'shortage'
  if (station.capacity > 0 && station.occupancyRate >= 80) return 'surplus'
  return 'normal'
}

function markerStyle(station: LiveStation, selected: boolean): L.CircleMarkerOptions {
  const status = stationStatus(station)
  const color = status === 'shortage' ? '#e5484d' : status === 'surplus' ? '#2878d0' : '#239a73'
  return {
    radius: selected ? 9 : 5,
    color: '#ffffff',
    weight: selected ? 3 : 1.5,
    fillColor: color,
    fillOpacity: selected ? 1 : 0.86,
    opacity: 1,
  }
}

function popupContent(station: LiveStation) {
  const root = document.createElement('div')
  root.className = 'leaflet-station-popup'

  const heading = document.createElement('strong')
  heading.textContent = station.stationName
  root.appendChild(heading)

  const id = document.createElement('small')
  id.textContent = station.stationId
  root.appendChild(id)

  const stock = document.createElement('p')
  stock.textContent = `현재 ${station.currentBikes}대 / 거치대 ${station.capacity}개 · 거치율 ${station.occupancyRate.toFixed(0)}%`
  root.appendChild(stock)
  return root
}

export function LeafletStationMap({ stations, selected, onSelect }: Props) {
  const elementRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<LeafletMap | null>(null)
  const layerRef = useRef<LayerGroup | null>(null)
  const markersRef = useRef<Map<string, MarkerRecord>>(new Map())
  const previousSelectedRef = useRef('')
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  useEffect(() => {
    if (!elementRef.current || mapRef.current) return
    const map = L.map(elementRef.current, {
      center: [37.5665, 126.978],
      zoom: 11,
      minZoom: 9,
      maxZoom: 19,
      zoomControl: true,
      preferCanvas: true,
    })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map)
    layerRef.current = L.layerGroup().addTo(map)
    mapRef.current = map

    const resizeObserver = new ResizeObserver(() => map.invalidateSize({ animate: false }))
    resizeObserver.observe(elementRef.current)
    return () => {
      resizeObserver.disconnect()
      map.remove()
      markersRef.current.clear()
      layerRef.current = null
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const layer = layerRef.current
    if (!layer) return
    layer.clearLayers()
    markersRef.current.clear()

    stations.forEach((station) => {
      if (!Number.isFinite(station.latitude) || !Number.isFinite(station.longitude)) return
      const marker = L.circleMarker(
        [station.latitude, station.longitude],
        markerStyle(station, station.stationId === selected),
      )
      marker.bindTooltip(`${station.stationName} · 현재 ${station.currentBikes}대`, {
        direction: 'top',
        offset: [0, -7],
      })
      marker.on('click', () => onSelectRef.current(station.stationId))
      marker.addTo(layer)
      markersRef.current.set(station.stationId, { marker, station })
    })
  }, [stations])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const previous = markersRef.current.get(previousSelectedRef.current)
    if (previous) previous.marker.setStyle(markerStyle(previous.station, false))

    const current = markersRef.current.get(selected)
    if (!current) {
      map.closePopup()
      previousSelectedRef.current = selected
      return
    }

    current.marker.setStyle(markerStyle(current.station, true))
    current.marker.bringToFront()
    if (previousSelectedRef.current && previousSelectedRef.current !== selected) {
      map.flyTo([current.station.latitude, current.station.longitude], 15, { duration: 0.35 })
    }
    current.marker.bindPopup(popupContent(current.station), {
      closeButton: false,
      offset: [0, -4],
      className: 'station-popup-shell',
    }).openPopup()
    previousSelectedRef.current = selected
  }, [selected, stations])

  return <div className="map-wrap leaflet-map-wrap">
    <div ref={elementRef} className="leaflet-map-canvas" aria-label="OpenStreetMap 기반 서울 대여소 지도" />
    <div className="map-legend"><span><i className="shortage" />▼ 부족</span><span><i className="surplus" />▲ 과잉</span><span><i className="normal" />● 정상</span></div>
  </div>
}
