export interface LongTermMemorySettings {
  enabled: boolean
  extract_profile_id: string
  consolidation_profile_id: string
  min_idle_seconds: number
  max_age_days: number
  max_unused_days: number
  max_extractions: number
  max_selected: number
  input_bytes: number
  consolidation_bytes: number
  lease_seconds: number
  retry_seconds: number
}

type NumericKey = Exclude<keyof LongTermMemorySettings, 'enabled' | 'extract_profile_id' | 'consolidation_profile_id'>
export const memoryNumericFields: { key: NumericKey; advanced: boolean; min: number }[] = [
  { key: 'min_idle_seconds', advanced: false, min: 0 },
  { key: 'max_age_days', advanced: false, min: 1 },
  { key: 'max_unused_days', advanced: false, min: 1 },
  { key: 'max_extractions', advanced: false, min: 1 },
  { key: 'max_selected', advanced: false, min: 1 },
  { key: 'input_bytes', advanced: true, min: 1 },
  { key: 'consolidation_bytes', advanced: true, min: 1 },
  { key: 'lease_seconds', advanced: true, min: 1 },
  { key: 'retry_seconds', advanced: true, min: 1 },
]
