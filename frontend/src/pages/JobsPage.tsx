import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Play, Square, RotateCcw, Trash2, ChevronRight, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { api } from '../lib/api'
import type { AutomationJob, JobStatus } from '../types'
import { formatDistanceToNow } from 'date-fns'

function StatusBadge({ status }: { status: JobStatus }) {
  const map: Record<JobStatus, string> = {
    running: 'badge-running',
    idle: 'badge-idle',
    error: 'badge-error',
    stopped: 'badge-stopped',
    paused: 'badge-stopped',
    recovering: 'badge-stopped',
  }
  return (
    <span className={map[status] ?? 'badge-idle'}>
      {status === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />}
      {status}
    </span>
  )
}

function CreateJobModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [interval, setInterval] = useState(15)
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      await api.post('/jobs', { name, target_url: url, poll_interval_seconds: interval })
      toast.success('Job created')
      onCreated()
      onClose()
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Failed to create job')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="card w-full max-w-md">
        <h2 className="text-base font-semibold text-white mb-4">New Automation Job</h2>
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="label">Job Name</label>
            <input className="input" placeholder="IndiaMART Lead Monitor" value={name} onChange={e => setName(e.target.value)} required />
          </div>
          <div>
            <label className="label">Target URL</label>
            <input className="input" placeholder="https://seller.indiamart.com/..." value={url} onChange={e => setUrl(e.target.value)} required />
          </div>
          <div>
            <label className="label">Poll Interval (seconds)</label>
            <input type="number" className="input" min={5} max={3600} value={interval} onChange={e => setInterval(+e.target.value)} required />
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-ghost flex-1 justify-center">Cancel</button>
            <button type="submit" disabled={loading} className="btn-primary flex-1 justify-center">
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Create Job
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function JobsPage() {
  const navigate = useNavigate()
  const [jobs, setJobs] = useState<AutomationJob[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({})

  useEffect(() => {
    fetchJobs()
    const timer = setInterval(fetchJobs, 10_000)
    return () => clearInterval(timer)
  }, [])

  async function fetchJobs() {
    try {
      const { data } = await api.get('/jobs')
      setJobs(data)
    } catch { toast.error('Failed to load jobs') }
    finally { setLoading(false) }
  }

  async function control(jobId: string, action: 'start' | 'stop' | 'restart') {
    setActionLoading(p => ({ ...p, [jobId]: true }))
    try {
      await api.post(`/jobs/${jobId}/control`, { action })
      toast.success(`Job ${action}ed`)
      fetchJobs()
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? `Failed to ${action} job`)
    } finally {
      setActionLoading(p => ({ ...p, [jobId]: false }))
    }
  }

  async function deleteJob(jobId: string) {
    if (!confirm('Delete this job? This cannot be undone.')) return
    try {
      await api.delete(`/jobs/${jobId}`)
      toast.success('Job deleted')
      fetchJobs()
    } catch { toast.error('Failed to delete job') }
  }

  return (
    <div className="p-6">
      {showCreate && <CreateJobModal onClose={() => setShowCreate(false)} onCreated={fetchJobs} />}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">Automation Jobs</h1>
          <p className="text-sm text-gray-500 mt-0.5">{jobs.length} configured job{jobs.length !== 1 ? 's' : ''}</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">
          <Plus size={14} /> New Job
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-48 text-gray-500">
          <Loader2 size={24} className="animate-spin" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-500 text-sm">No automation jobs yet.</p>
          <button onClick={() => setShowCreate(true)} className="btn-primary mt-4 mx-auto">
            <Plus size={14} /> Create your first job
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map(job => (
            <div key={job.id} className="card hover:border-gray-700 transition-colors">
              <div className="flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-medium text-white truncate">{job.name}</h3>
                    <StatusBadge status={job.status} />
                  </div>
                  <p className="text-xs text-gray-500 truncate">{job.target_url}</p>
                  <div className="flex items-center gap-4 mt-1.5 text-xs text-gray-600">
                    <span>Leads: <span className="text-purple-400 font-medium">{job.total_leads_detected}</span></span>
                    <span>Actions: <span className="text-blue-400 font-medium">{job.total_actions_executed}</span></span>
                    <span>Errors: <span className={clsx(job.error_count > 0 ? 'text-red-400' : 'text-gray-600', 'font-medium')}>{job.error_count}</span></span>
                    {job.last_heartbeat && (
                      <span>Heartbeat: {formatDistanceToNow(new Date(job.last_heartbeat), { addSuffix: true })}</span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {actionLoading[job.id] ? (
                    <Loader2 size={16} className="animate-spin text-gray-500" />
                  ) : (
                    <>
                      {job.status !== 'running' ? (
                        <button onClick={() => control(job.id, 'start')} className="p-2 rounded-lg bg-green-900/40 hover:bg-green-900/70 text-green-400 transition-colors" title="Start">
                          <Play size={14} />
                        </button>
                      ) : (
                        <button onClick={() => control(job.id, 'stop')} className="p-2 rounded-lg bg-yellow-900/40 hover:bg-yellow-900/70 text-yellow-400 transition-colors" title="Stop">
                          <Square size={14} />
                        </button>
                      )}
                      <button onClick={() => control(job.id, 'restart')} className="p-2 rounded-lg bg-blue-900/40 hover:bg-blue-900/70 text-blue-400 transition-colors" title="Restart">
                        <RotateCcw size={14} />
                      </button>
                      <button onClick={() => deleteJob(job.id)} className="p-2 rounded-lg bg-red-900/40 hover:bg-red-900/70 text-red-400 transition-colors" title="Delete">
                        <Trash2 size={14} />
                      </button>
                    </>
                  )}
                  <button onClick={() => navigate(`/dashboard/jobs/${job.id}`)} className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 transition-colors" title="Details">
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
