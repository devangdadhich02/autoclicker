import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Plus, Trash2, ToggleLeft, ToggleRight, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../lib/api'
import type { AutomationJob, Keyword, ActionRule } from '../types'

export default function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const [job, setJob] = useState<AutomationJob | null>(null)
  const [keywords, setKeywords] = useState<Keyword[]>([])
  const [actions, setActions] = useState<ActionRule[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'keywords' | 'actions'>('keywords')

  // New keyword form
  const [kwValue, setKwValue] = useState('')
  const [kwType, setKwType] = useState('contains')
  const [kwPriority, setKwPriority] = useState(5)
  const [kwSaving, setKwSaving] = useState(false)

  // New action form
  const [actName, setActName] = useState('')
  const [actType, setActType] = useState('click')
  const [actSelector, setActSelector] = useState('')
  const [actSaving, setActSaving] = useState(false)

  useEffect(() => {
    if (jobId) {
      fetchAll()
      const timer = setInterval(() => fetchAll(true), 5_000)
      return () => clearInterval(timer)
    }
  }, [jobId])

  async function fetchAll(silent = false) {
    if (!silent) setLoading(true)
    try {
      const [j, kw, act] = await Promise.all([
        api.get(`/jobs/${jobId}`),
        api.get(`/jobs/${jobId}/keywords`),
        api.get(`/jobs/${jobId}/actions`),
      ])
      setJob(j.data)
      setKeywords(kw.data)
      setActions(act.data)
    } catch { if (!silent) toast.error('Failed to load job') }
    finally { if (!silent) setLoading(false) }
  }

  async function addKeyword(e: React.FormEvent) {
    e.preventDefault()
    setKwSaving(true)
    try {
      await api.post(`/jobs/${jobId}/keywords`, { value: kwValue, match_type: kwType, priority: kwPriority })
      toast.success('Keyword added')
      setKwValue('')
      await fetchAll()
    } catch (err: any) { toast.error(err?.response?.data?.detail ?? 'Failed') }
    finally { setKwSaving(false) }
  }

  async function deleteKeyword(kwId: string) {
    await api.delete(`/jobs/${jobId}/keywords/${kwId}`)
    toast.success('Keyword removed')
    await fetchAll()
  }

  async function toggleKeyword(kw: Keyword) {
    await api.patch(`/jobs/${jobId}/keywords/${kw.id}`, { is_active: !kw.is_active })
    await fetchAll()
  }

  async function addAction(e: React.FormEvent) {
    e.preventDefault()
    setActSaving(true)
    try {
      await api.post(`/jobs/${jobId}/actions`, { name: actName, action_type: actType, selector: actSelector || null })
      toast.success('Action rule added')
      setActName(''); setActSelector('')
      await fetchAll()
    } catch (err: any) { toast.error(err?.response?.data?.detail ?? 'Failed') }
    finally { setActSaving(false) }
  }

  async function deleteAction(ruleId: string) {
    await api.delete(`/jobs/${jobId}/actions/${ruleId}`)
    toast.success('Action removed')
    await fetchAll()
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-gray-500">
      <Loader2 size={24} className="animate-spin" />
    </div>
  )
  if (!job) return <div className="p-6 text-gray-500">Job not found.</div>

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/dashboard/jobs')} className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 transition-colors">
          <ArrowLeft size={14} />
        </button>
        <div>
          <h1 className="text-xl font-bold text-white">{job.name}</h1>
          <p className="text-xs text-gray-500">{job.target_url}</p>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Status', value: job.status },
          { label: 'Leads Detected', value: job.total_leads_detected },
          { label: 'Actions Executed', value: job.total_actions_executed },
          { label: 'Errors', value: job.error_count },
        ].map(({ label, value }) => (
          <div key={label} className="card py-3">
            <p className="text-lg font-bold text-white">{value}</p>
            <p className="text-xs text-gray-500">{label}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-lg p-1 w-fit">
        {(['keywords', 'actions'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 text-sm rounded-md font-medium transition-colors capitalize ${tab === t ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
            {t} {t === 'keywords' ? `(${keywords.length})` : `(${actions.length})`}
          </button>
        ))}
      </div>

      {/* Keywords tab */}
      {tab === 'keywords' && (
        <div className="space-y-4">
          <form onSubmit={addKeyword} className="card flex gap-3 items-end flex-wrap">
            <div className="flex-1 min-w-[160px]">
              <label className="label">Keyword</label>
              <input className="input" placeholder="steel pipe" value={kwValue} onChange={e => setKwValue(e.target.value)} required />
            </div>
            <div className="w-36">
              <label className="label">Match Type</label>
              <select className="input" value={kwType} onChange={e => setKwType(e.target.value)}>
                {['contains', 'exact', 'regex', 'starts_with', 'ends_with'].map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="w-24">
              <label className="label">Priority</label>
              <input type="number" className="input" min={1} max={10} value={kwPriority} onChange={e => setKwPriority(+e.target.value)} />
            </div>
            <button type="submit" disabled={kwSaving} className="btn-primary">
              {kwSaving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Add
            </button>
          </form>

          <div className="space-y-2">
            {keywords.length === 0 && <p className="text-gray-500 text-sm text-center py-6">No keywords yet. Add one above.</p>}
            {keywords.map(kw => (
              <div key={kw.id} className="card flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white">{kw.value}</p>
                  <p className="text-xs text-gray-500">{kw.match_type} · priority {kw.priority} · matched {kw.match_count}x</p>
                </div>
                <button onClick={() => toggleKeyword(kw)} className={kw.is_active ? 'text-green-400' : 'text-gray-600'}>
                  {kw.is_active ? <ToggleRight size={20} /> : <ToggleLeft size={20} />}
                </button>
                <button onClick={() => deleteKeyword(kw.id)} className="text-gray-600 hover:text-red-400 transition-colors">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions tab */}
      {tab === 'actions' && (
        <div className="space-y-4">
          <form onSubmit={addAction} className="card flex gap-3 items-end flex-wrap">
            <div className="flex-1 min-w-[140px]">
              <label className="label">Action Name</label>
              <input className="input" placeholder="Open Inquiry" value={actName} onChange={e => setActName(e.target.value)} required />
            </div>
            <div className="w-40">
              <label className="label">Action Type</label>
              <select className="input" value={actType} onChange={e => setActType(e.target.value)}>
                {['click', 'navigate', 'screenshot', 'webhook', 'notify', 'open_inquiry', 'mark_important', 'extract_text', 'wait'].map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="flex-1 min-w-[140px]">
              <label className="label">CSS Selector (optional)</label>
              <input className="input" placeholder=".lead-item button" value={actSelector} onChange={e => setActSelector(e.target.value)} />
            </div>
            <button type="submit" disabled={actSaving} className="btn-primary">
              {actSaving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Add
            </button>
          </form>

          <div className="space-y-2">
            {actions.length === 0 && <p className="text-gray-500 text-sm text-center py-6">No action rules yet.</p>}
            {actions.map(rule => (
              <div key={rule.id} className="card flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white">{rule.name}</p>
                  <p className="text-xs text-gray-500">{rule.action_type}{rule.selector ? ` · ${rule.selector}` : ''} · executed {rule.execution_count}x</p>
                </div>
                <button onClick={() => deleteAction(rule.id)} className="text-gray-600 hover:text-red-400 transition-colors">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
