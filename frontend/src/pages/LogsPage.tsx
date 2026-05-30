import { useEffect, useState } from 'react'
import { Download, RefreshCw, Filter } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'
import { api } from '../lib/api'
import type { EventLog, EventSeverity } from '../types'

const SEVERITIES: EventSeverity[] = ['debug', 'info', 'warning', 'error', 'critical']

const SEV_CLS: Record<EventSeverity, string> = {
  debug: 'bg-gray-800 text-gray-400',
  info: 'bg-blue-900/50 text-blue-400',
  warning: 'bg-yellow-900/50 text-yellow-400',
  error: 'bg-red-900/50 text-red-400',
  critical: 'bg-red-900 text-red-200 font-semibold',
}

export default function LogsPage() {
  const [logs, setLogs] = useState<EventLog[]>([])
  const [loading, setLoading] = useState(true)
  const [filterSev, setFilterSev] = useState<EventSeverity | ''>('')
  const [filterType, setFilterType] = useState('')
  const [limit, setLimit] = useState(100)

  useEffect(() => {
    fetchLogs()
    const timer = setInterval(() => fetchLogs(true), 10_000)
    return () => clearInterval(timer)
  }, [filterSev, limit])

  async function fetchLogs(silent = false) {
    if (!silent) setLoading(true)
    try {
      const params: Record<string, string | number> = { limit }
      if (filterSev) params.severity = filterSev
      if (filterType) params.event_type = filterType
      const { data } = await api.get('/logs', { params })
      setLogs(data)
    } catch {} finally { if (!silent) setLoading(false) }
  }

  async function exportCsv() {
    const params: Record<string, string | number> = { limit: 5000 }
    if (filterSev) params.severity = filterSev
    const resp = await api.get('/logs/export/csv', { params, responseType: 'blob' })
    const url = URL.createObjectURL(resp.data)
    const a = document.createElement('a')
    a.href = url; a.download = 'velora_logs.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  async function exportLeadsCsv() {
    const resp = await api.get('/logs/export/leads/csv', { params: { limit: 5000 }, responseType: 'blob' })
    const url = URL.createObjectURL(resp.data)
    const a = document.createElement('a')
    a.href = url; a.download = 'velora_leads.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Event Logs</h1>
          <p className="text-sm text-gray-500 mt-0.5">{logs.length} entries shown</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => fetchLogs()} className="btn-ghost py-1.5 px-3 text-xs"><RefreshCw size={12} /> Refresh</button>
          <button onClick={exportLeadsCsv} className="btn-primary py-1.5 px-3 text-xs"><Download size={12} /> Export Leads CSV</button>
          <button onClick={exportCsv} className="btn-ghost py-1.5 px-3 text-xs"><Download size={12} /> All Logs CSV</button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter size={13} className="text-gray-500" />
          <select className="input w-36 py-1.5 text-xs" value={filterSev} onChange={e => setFilterSev(e.target.value as any)}>
            <option value="">All Severities</option>
            {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <input className="input w-48 py-1.5 text-xs" placeholder="Event type filter..." value={filterType}
          onChange={e => setFilterType(e.target.value)} onKeyDown={e => e.key === 'Enter' && fetchLogs()} />
        <select className="input w-28 py-1.5 text-xs" value={limit} onChange={e => setLimit(+e.target.value)}>
          {[50, 100, 250, 500].map(n => <option key={n} value={n}>Last {n}</option>)}
        </select>
      </div>

      {/* Log table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500">
                <th className="px-4 py-3 text-left font-medium">Severity</th>
                <th className="px-4 py-3 text-left font-medium">Type</th>
                <th className="px-4 py-3 text-left font-medium">Message</th>
                <th className="px-4 py-3 text-left font-medium">Keyword</th>
                <th className="px-4 py-3 text-left font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-600">Loading...</td></tr>
              )}
              {!loading && logs.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-600">No logs found</td></tr>
              )}
              {!loading && logs.map(log => (
                <tr key={log.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                  <td className="px-4 py-2.5">
                    <span className={clsx('px-1.5 py-0.5 rounded text-xs uppercase', SEV_CLS[log.severity] ?? SEV_CLS.info)}>
                      {log.severity}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-400 font-mono">{log.event_type}</td>
                  <td className="px-4 py-2.5 text-gray-300 max-w-md truncate">{log.message}</td>
                  <td className="px-4 py-2.5 text-blue-400">{log.keyword_matched ?? '—'}</td>
                  <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">
                    {log.created_at ? formatDistanceToNow(new Date(log.created_at), { addSuffix: true }) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
