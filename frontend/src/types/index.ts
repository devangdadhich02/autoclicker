export type UserRole = 'admin' | 'operator' | 'viewer'

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  is_verified: boolean
  created_at: string
  updated_at: string
}

export type JobStatus = 'idle' | 'running' | 'paused' | 'error' | 'stopped' | 'recovering'

export interface AutomationJob {
  id: string
  owner_id: string
  name: string
  description: string | null
  target_url: string
  status: JobStatus
  is_active: boolean
  poll_interval_seconds: number
  last_heartbeat: string | null
  last_error: string | null
  error_count: number
  restart_count: number
  total_actions_executed: number
  total_leads_detected: number
  browser_profile_name: string | null
  scheduler_cron: string | null
  created_at: string
  updated_at: string
}

export type MatchType = 'exact' | 'contains' | 'regex' | 'starts_with' | 'ends_with'

export interface Keyword {
  id: string
  job_id: string
  value: string
  match_type: MatchType
  case_sensitive: boolean
  priority: number
  score: number
  category: string | null
  location_filter: string | null
  is_active: boolean
  cooldown_seconds: number
  match_count: number
  created_at: string
  updated_at: string
}

export type ActionType =
  | 'click'
  | 'navigate'
  | 'fill_form'
  | 'extract_text'
  | 'screenshot'
  | 'wait'
  | 'scroll'
  | 'webhook'
  | 'notify'
  | 'mark_important'
  | 'open_inquiry'
  | 'copy_lead'

export interface ActionRule {
  id: string
  job_id: string
  name: string
  action_type: ActionType
  selector: string | null
  fallback_selector: string | null
  target_url: string | null
  payload: string | null
  order: number
  is_active: boolean
  retry_count: number
  timeout_ms: number
  delay_after_ms: number
  execution_count: number
  created_at: string
  updated_at: string
}

export type EventSeverity = 'debug' | 'info' | 'warning' | 'error' | 'critical'

export interface EventLog {
  id: string
  job_id: string | null
  severity: EventSeverity
  event_type: string
  message: string
  details: string | null
  screenshot_path: string | null
  keyword_matched: string | null
  created_at: string
}

export interface AnalyticsSummary {
  total_jobs: number
  running_jobs: number
  total_leads_detected: number
  total_actions_executed: number
  total_errors: number
  severity_breakdown: Record<string, number>
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}
