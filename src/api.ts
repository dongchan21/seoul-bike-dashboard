export type DataQuality = 'normal' | 'delayed'

export interface InventoryStatus {
  runId: string
  slot: string
  startedAt: string
  finishedAt: string
  stationCount: number
  ageSeconds: number
  dataQuality: DataQuality
  lastRunStatus: string | null
  lastRunError: string | null
  predictionModel: {
    modelVersion: string
    trainedAt: string
    trainingStart: string
    trainingEnd: string
    trainingRows: number
    stationCount: number
    horizonMinutes: number
    method: string
  } | null
}

export interface LiveStation {
  stationId: string
  stationName: string
  capacity: number
  currentBikes: number
  occupancyRate: number
  latitude: number
  longitude: number
  fetchedAt: string
  slot: string
  predictionAvailable: boolean
  district: string | null
  address: string | null
  expectedRentals30m: number | null
  expectedReturns30m: number | null
  expectedBikes30m: number | null
  forecastStatus: 'shortage' | 'normal' | 'surplus' | null
  recommendedAction: 'replenish' | 'collect' | 'none' | null
  recommendedQuantity: number
  priority: number | null
  predictionAsOf: string | null
  modelVersion: string | null
}

export interface InventoryPoint {
  currentBikes: number
  occupancyRate: number
  fetchedAt: string
  slot: string
}

async function readJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail ?? `요청에 실패했습니다. (HTTP ${response.status})`)
  }
  return response.json() as Promise<T>
}

export async function fetchInventory(signal?: AbortSignal) {
  const [stations, status] = await Promise.all([
    readJson<LiveStation[]>('/api/stations', signal),
    readJson<InventoryStatus>('/api/status', signal),
  ])
  return { stations, status }
}

export function fetchStationHistory(stationId: string, signal?: AbortSignal) {
  return readJson<InventoryPoint[]>(
    `/api/stations/${encodeURIComponent(stationId)}/history?limit=13`,
    signal,
  )
}
