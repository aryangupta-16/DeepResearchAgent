export type MemoryType =
  | 'preference'
  | 'interest'
  | 'goal'
  | 'context'
  | 'instruction'
  | 'fact'

export type MemorySource = 'explicit' | 'inferred'

export interface Memory {
  id: string
  owner_id: string
  content: string
  memory_type: MemoryType
  source: MemorySource
  importance: number
  created_at: string
  updated_at: string
  last_used_at: string | null
  use_count: number
  is_active: boolean
}

export interface MemoryListResponse {
  memories: Memory[]
  count: number
}

export interface MemoryCreate {
  content: string
  memory_type?: MemoryType
  source?: MemorySource
  importance?: number
}

export interface MemoryUpdate {
  content?: string
  memory_type?: MemoryType
  importance?: number
  is_active?: boolean
}
