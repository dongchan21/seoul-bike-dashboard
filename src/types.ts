export type Status = 'shortage' | 'normal' | 'surplus'
export type DataHealth = 'normal' | 'delayed' | 'missing'

export interface StationSeed {
  id: string; name: string; district: string; lat: number; lng: number
  capacity: number; base: number; bias: number; dataHealth?: DataHealth
}

export interface Station extends StationSeed {
  current: number; rentals: number; returns: number; expected: number
  recommendation: number; status: Status; priority: number; collectedAt: Date
  history: number[]; forecast: number[]; historicalAvg: number[]
}

export interface RouteRecommendation {
  from: Station; to: Station; quantity: number; distance: number
  fromAfter: number; toAfter: number
}
