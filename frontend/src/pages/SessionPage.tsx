import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  RefreshCw, Loader2, CheckCircle2, AlertTriangle, XCircle,
  Cookie, ChevronDown, ChevronUp,
} from 'lucide-react'
import { formatDistanceToNow, format } from 'date-fns'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { api } from '../lib/api'
import type { BrowserProfileStatus } from '../types'

const LOGIN_PROFILE = 'indiamart'

type SessionState = 'active' | 'missing' | 'incomplete'

function resolveSessionState(profile: BrowserProfileStatus | null): SessionState {
  if (!profile || profile.status === 'missing') return 'missing'
  if (profile.status === 'ready') return 'active'
  return 'incomplete'
}

const STATE_UI: Record<
  SessionState,
  {
    answer: string
    title: string
    subtitle: string
    icon: typeof CheckCircle2
    iconClass: string
    panelClass: string
    badgeClass: string
  }
> = {
  active: {
    answer: 'YES',
    title: 'IndiaMART seller session is on the server',
    subtitle: 'You logged in via login.ps1 and the seller session was uploaded successfully. Automation can use this login.',
    icon: CheckCircle2,
    iconClass: 'text-green-400',
    panelClass: 'border-green-700/60 bg-green-950/30',
    badgeClass: 'bg-green-900/50 text-green-300 border-green-700',
  },
  missing: {
    answer: 'NO',
    title: 'IndiaMART seller session is NOT on the server',
    subtitle: 'No seller login was found. Run login.ps1 on your laptop, sign in to seller.indiamart.com, then click Refresh.',
    icon: XCircle,
    iconClass: 'text-red-400',
    panelClass: 'border-red-800/60 bg-red-950/20',
    badgeClass: 'bg-red-900/50 text-red-300 border-red-800',
  },
  incomplete: {
    answer: 'NO',
    title: 'IndiaMART seller session is NOT valid yet',
    subtitle: 'Something was uploaded but it is not a complete seller login. Run login.ps1 again and sign in fully before pressing Enter.',
    icon: AlertTriangle,
    iconClass: 'text-amber-400',
    panelClass: 'border-amber-800/60 bg-amber-950/20',
    badgeClass: 'bg-amber-900/50 text-amber-200 border-amber-700',
  },
}

function CheckItem({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      {ok ? (
        <CheckCircle2 size={16} className="text-green-400 shrink-0" />
      ) : (
        <XCircle size={16} className="text-red-400 shrink-0" />
      )}
      <span className={ok ? 'text-gray-300' : 'text-gray-400'}>{label}</span>
    </li>
  )
}

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

export default function SessionPage() {
  const [profile, setProfile] = useState<BrowserProfileStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [showSetup, setShowSetup] = useState(true)
  const [showDetails, setShowDetails] = useState(false)

  useEffect(() => {
    fetchSession()
    const t = setInterval(() => fetchSession(true), 15_000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (profile?.status === 'ready') setShowSetup(false)
  }, [profile?.status])

  async function fetchSession(silent = false) {
    if (!silent) {
      setLoading(true)
      setProfile(null)
    }
    try {
      const { data } = await api.get(`/profiles/${LOGIN_PROFILE}`)
      setProfile(data)
    } catch {
      setProfile(null)
      if (!silent) toast.error('Could not load session status')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  const state = resolveSessionState(profile)
  const ui = STATE_UI[state]
  const Icon = ui.icon
  const jobLinked = (profile?.linked_jobs.length ?? 0) > 0
  const filesOk = (profile?.file_count ?? 0) >= 10
  const cookiesOk = profile?.has_cookies ?? false

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white">IndiaMART Seller Session</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Is your seller.indiamart.com login saved on the server?
          </p>
        </div>
        <button type="button" onClick={() => fetchSession()} className="btn-ghost py-1.5 px-3 text-xs">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {loading ? (
        <div className="card flex justify-center py-20 text-gray-500">
          <Loader2 size={28} className="animate-spin" />
        </div>
      ) : (
        <>
          {/* Primary answer */}
          <div className={clsx('card border-2 p-6 space-y-4', ui.panelClass)}>
            <p className="text-xs font-medium uppercase tracking-wider text-gray-500">
              Seller session on server?
            </p>
            <p
              className={clsx(
                'text-5xl font-black tracking-tight',
                state === 'active' ? 'text-green-400' : 'text-red-400',
              )}
            >
              {ui.answer}
            </p>

            <div className="flex flex-col sm:flex-row sm:items-start gap-4 pt-2">
              <div className={clsx('w-12 h-12 rounded-xl flex items-center justify-center bg-gray-900/80 shrink-0')}>
                <Icon size={28} className={ui.iconClass} />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-bold text-white">{ui.title}</h2>
                <p className="text-sm text-gray-400 mt-1">{ui.subtitle}</p>
                {profile?.status_message && state !== 'active' && (
                  <p className="text-xs text-gray-500 mt-2 border-l-2 border-gray-700 pl-2">
                    {profile.status_message}
                  </p>
                )}
              </div>
            </div>

            <ul className="space-y-2 pt-2 border-t border-gray-800/80">
              <CheckItem
                ok={state === 'active'}
                label="IndiaMART seller session is valid (only YES above means you are ready)"
              />
              <CheckItem ok={filesOk} label={`Seller profile files uploaded (${profile?.file_count ?? 0} files, need 10+)`} />
              <CheckItem ok={cookiesOk} label="Seller login cookies saved" />
              <CheckItem ok={jobLinked} label={`Automation job uses profile "${LOGIN_PROFILE}"`} />
            </ul>

            {state === 'active' && !jobLinked && (
              <p className="text-sm text-amber-200/90 bg-amber-950/40 border border-amber-800/50 rounded-lg px-3 py-2">
                Open your job settings and set <strong>Browser Profile Name</strong> to{' '}
                <code className="text-amber-100">{LOGIN_PROFILE}</code>, then restart the job.
              </p>
            )}
          </div>

          {/* Setup — collapsed by default when session active */}
          <div className="card">
            <button
              type="button"
              onClick={() => setShowSetup(!showSetup)}
              className="flex w-full items-center justify-between text-sm font-semibold text-white"
            >
              How to upload session (login.ps1)
              {showSetup ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {showSetup && (
              <div className="mt-4 space-y-3">
                <pre className="text-xs text-gray-400 whitespace-pre-wrap font-mono leading-relaxed bg-gray-900/60 rounded-lg p-3 border border-gray-800">
{`Invoke-WebRequest -Uri "https://raw.githubusercontent.com/devangdadhich02/autoclicker/main/scripts/login_and_upload.ps1" -OutFile "login.ps1"
.\\login.ps1`}
                </pre>
                <ol className="text-xs text-gray-500 space-y-1 list-decimal list-inside">
                  <li>Chrome opens on your laptop — log in to IndiaMART seller account</li>
                  <li>Return to PowerShell and press Enter</li>
                  <li>Wait for SUCCESS message</li>
                  <li>Click Refresh on this page — large green YES should appear</li>
                </ol>
              </div>
            )}
          </div>

          {/* Technical details */}
          {profile && (
            <div className="card">
              <button
                type="button"
                onClick={() => setShowDetails(!showDetails)}
                className="flex w-full items-center justify-between text-sm font-semibold text-white"
              >
                Technical details
                {showDetails ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {showDetails && (
                <dl className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div>
                    <dt className="text-gray-500">Profile name</dt>
                    <dd className="text-gray-200 font-medium">{profile.profile_name}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Current session uploaded</dt>
                    <dd className="text-gray-200 font-medium">
                      {profile.uploaded_at
                        ? `${format(new Date(profile.uploaded_at), 'dd MMM yyyy HH:mm')} (${formatDistanceToNow(new Date(profile.uploaded_at), { addSuffix: true })})`
                        : 'Not recorded — re-run login.ps1'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Size</dt>
                    <dd className="text-gray-200 font-medium">
                      {formatBytes(profile.size_bytes)} · {profile.file_count} files
                    </dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Local storage</dt>
                    <dd className="text-gray-200 font-medium">{profile.has_local_storage ? 'Yes' : 'No'}</dd>
                  </div>
                  {profile.login_url && (
                    <div className="sm:col-span-2">
                      <dt className="text-gray-500">Login URL</dt>
                      <dd className="text-gray-200 font-medium truncate">{profile.login_url}</dd>
                    </div>
                  )}
                </dl>
              )}
              {profile.linked_jobs.length > 0 && (
                <div className="mt-4 pt-3 border-t border-gray-800">
                  <p className="text-xs text-gray-500 mb-2">Linked jobs</p>
                  <ul className="space-y-1">
                    {profile.linked_jobs.map((j) => (
                      <li key={j.id}>
                        <Link to={`/dashboard/jobs/${j.id}`} className="text-sm text-blue-400 hover:text-blue-300">
                          {j.name} <span className="text-gray-500">({j.status})</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <p className="text-xs text-gray-600 flex items-center gap-1.5">
            <Cookie size={12} />
            This page shows only the <strong className="text-gray-500">current</strong> seller session on the server.
            Old sessions are not listed. After login.ps1, click Refresh — previous details disappear and new ones appear.
          </p>
        </>
      )}
    </div>
  )
}
