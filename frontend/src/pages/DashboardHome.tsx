import { useEffect, useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Activity, TrendingUp, AlertTriangle, Play, Zap, RefreshCw, Cookie, ChevronRight } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import axios from 'axios'
import { api } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import type { AnalyticsSummary, BrowserProfileStatus, EventLog } from '../types'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

const SEV_COLORS: Record<string, string> = {
  debug: '#6b7280', info: '#3b82f6', warning: '#f59e0b', error: '#ef4444', critical: '#dc2626',
}

function StatCard({ label, value, icon: Icon, color }: { label: string; value: number | string; icon: any; color: string }) {
  return (
    <div className="card flex items-center gap-4">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color}`}>
        <Icon size={18} />
      </div>
      <div>
        <p className="text-2xl font-bold text-white">{value}</p>
        <p className="text-xs text-gray-500">{label}</p>
      </div>
    </div>
  )
}

function SeverityBadge({ sev }: { sev: string }) {
  const cls: Record<string, string> = {
    debug: 'bg-gray-800 text-gray-400',
    info: 'bg-blue-900/50 text-blue-400',
    warning: 'bg-yellow-900/50 text-yellow-400',
    error: 'bg-red-900/50 text-red-400',
    critical: 'bg-red-900 text-red-300',
  }
  return (
    <span className={clsx('px-1.5 py-0.5 rounded text-xs font-medium uppercase', cls[sev] ?? cls.info)}>
      {sev}
    </span>
  )
}

export default function DashboardHome() {
  const { accessToken } = useAuthStore()
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null)
  const [logs, setLogs] = useState<EventLog[]>([])
  const [session, setSession] = useState<BrowserProfileStatus | null>(null)
  const [wsLive, setWsLive] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    fetchData()
    connectWs()
    return () => {
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [accessToken])

  async function refreshAccessToken(): Promise<string | null> {
    const refreshToken = useAuthStore.getState().refreshToken
    if (!refreshToken) return null
    try {
      const { data } = await axios.post(`${import.meta.env.VITE_API_URL || '/api/v1'}/auth/refresh`, {
        refresh_token: refreshToken,
      })
      useAuthStore.getState().setTokens(data.access_token, data.refresh_token)
      return data.access_token as string
    } catch {
      useAuthStore.getState().logout()
      window.location.href = '/login'
      return null
    }
  }

  async function fetchData() {
    try {
      const [sumRes, logRes, profRes] = await Promise.all([
        api.get('/logs/analytics/summary'),
        api.get('/logs?limit=20'),
        api.get('/profiles/indiamart').catch(() => ({ data: null })),
      ])
      setSummary(sumRes.data)
      setLogs(logRes.data)
      setSession(profRes.data)
    } catch {}
  }

  function connectWs() {
    const token = useAuthStore.getState().accessToken
    if (!token) return
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host = window.location.host
    const ws = new WebSocket(`${proto}://${host}/api/v1/ws/dashboard?token=${token}`)
    wsRef.current = ws

    ws.onopen = () => setWsLive(true)
    ws.onclose = async () => {
      setWsLive(false)
      const fresh = await refreshAccessToken()
      if (fresh) {
        setTimeout(connectWs, 1000)
      }
    }
    ws.onerror = () => ws.close()
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'dashboard_update') {
        setLogs(msg.recent_logs ?? [])
      }
    }
  }

  const chartData = summary
    ? Object.entries(summary.severity_breakdown).map(([k, v]) => ({ name: k, count: v }))
    : []

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Overview</h1>
          <p className="text-sm text-gray-500 mt-0.5">Real-time automation monitoring</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={clsx('flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border',
            wsLive ? 'text-green-400 border-green-800 bg-green-900/30' : 'text-gray-500 border-gray-700 bg-gray-800/50'
          )}>
            <span className={clsx('w-1.5 h-1.5 rounded-full', wsLive ? 'bg-green-400 animate-pulse' : 'bg-gray-600')} />
            {wsLive ? 'Live' : 'Connecting...'}
          </span>
          <button onClick={fetchData} className="btn-ghost py-1.5 px-3 text-xs">
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* IndiaMART session strip */}
      <Link
        to="/dashboard/session"
        className={clsx(
          'card flex items-center justify-between gap-4 transition-colors hover:border-gray-600',
          session?.status === 'ready' && 'border-green-800/60 bg-green-950/20',
          session?.status === 'incomplete' && 'border-yellow-800/60 bg-yellow-950/20',
          session?.status === 'missing' && 'border-red-800/50 bg-red-950/10',
        )}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className={clsx(
            'w-10 h-10 rounded-lg flex items-center justify-center shrink-0',
            session?.status === 'ready' ? 'bg-green-900/50 text-green-400' : 'bg-gray-800 text-gray-400',
          )}>
            <Cookie size={18} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-white">IndiaMART seller session</p>
            <p className="text-xs text-gray-500 truncate">
              {session?.status === 'ready'
                ? 'YES — seller login is on the server'
                : 'NO — seller login missing or invalid'}
            </p>
            {session?.uploaded_at && (
              <p className="text-xs text-gray-600 mt-0.5">
                Uploaded {formatDistanceToNow(new Date(session.uploaded_at), { addSuffix: true })}
              </p>
            )}
          </div>
        </div>
        <ChevronRight size={18} className="text-gray-500 shrink-0" />
      </Link>

      {/* Stats */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Total Jobs" value={summary.total_jobs} icon={Zap} color="bg-blue-900/50 text-blue-400" />
          <StatCard label="Running" value={summary.running_jobs} icon={Play} color="bg-green-900/50 text-green-400" />
          <StatCard label="Leads Detected" value={summary.total_leads_detected} icon={TrendingUp} color="bg-purple-900/50 text-purple-400" />
          <StatCard label="Total Errors" value={summary.total_errors} icon={AlertTriangle} color="bg-red-900/50 text-red-400" />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Severity chart */}
        <div className="card lg:col-span-1">
          <h2 className="text-sm font-semibold text-white mb-4">Event Severity Breakdown</h2>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={chartData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                  labelStyle={{ color: '#f9fafb' }}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {chartData.map((entry) => (
                    <Cell key={entry.name} fill={SEV_COLORS[entry.name] ?? '#6b7280'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[180px] flex items-center justify-center text-gray-600 text-sm">No data yet</div>
          )}
        </div>

        {/* Live log feed */}
        <div className="card lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-white">Recent Events</h2>
            <Activity size={14} className="text-gray-500" />
          </div>
          <div className="space-y-2 max-h-[220px] overflow-y-auto pr-1">
            {logs.length === 0 && (
              <p className="text-sm text-gray-600 py-4 text-center">No events yet</p>
            )}
            {logs.map((log) => (
              <div key={log.id} className="flex items-start gap-3 py-2 border-b border-gray-800 last:border-0">
                <SeverityBadge sev={log.severity} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-300 truncate">{log.message}</p>
                  {log.keyword_matched && (
                    <p className="text-xs text-blue-400 mt-0.5">Keyword: {log.keyword_matched}</p>
                  )}
                </div>
                <span className="text-xs text-gray-600 whitespace-nowrap shrink-0">
                  {log.created_at ? formatDistanceToNow(new Date(log.created_at), { addSuffix: true }) : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
