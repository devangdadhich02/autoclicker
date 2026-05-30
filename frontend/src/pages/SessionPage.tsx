import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  RefreshCw, Loader2, CheckCircle2, AlertCircle, XCircle,
  Cookie, HardDrive, Clock, Link2, ExternalLink,
} from 'lucide-react'
import { formatDistanceToNow, format } from 'date-fns'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { api } from '../lib/api'
import type { BrowserProfileStatus } from '../types'

function StatusBadge({ status }: { status: string }) {
  if (status === 'ready') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-green-900/40 text-green-400 border border-green-800">
        <CheckCircle2 size={14} /> Session received
      </span>
    )
  }
  if (status === 'incomplete') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-yellow-900/40 text-yellow-400 border border-yellow-800">
        <AlertCircle size={14} /> Incomplete
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-red-900/40 text-red-400 border border-red-800">
      <XCircle size={14} /> Not uploaded
    </span>
  )
}

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

function ProfileCard({ profile }: { profile: BrowserProfileStatus }) {
  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white capitalize">{profile.profile_name}</h2>
          <p className="text-sm text-gray-400 mt-0.5">{profile.status_message}</p>
        </div>
        <StatusBadge status={profile.status} />
      </div>

      {profile.status === 'ready' && (
        <div className="rounded-lg bg-green-900/20 border border-green-800/50 px-4 py-3 text-sm text-green-300">
          IndiaMART login session server par mil gayi hai. Ab job start karo — automation isi session se chalegi.
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        <DetailRow
          icon={Clock}
          label="Uploaded"
          value={
            profile.uploaded_at
              ? `${format(new Date(profile.uploaded_at), 'dd MMM yyyy, HH:mm')} (${formatDistanceToNow(new Date(profile.uploaded_at), { addSuffix: true })})`
              : '—'
          }
        />
        <DetailRow
          icon={HardDrive}
          label="Profile size"
          value={`${formatBytes(profile.size_bytes)} · ${profile.file_count} files`}
        />
        <DetailRow
          icon={Cookie}
          label="Cookies saved"
          value={profile.has_cookies ? 'Yes' : 'No'}
          ok={profile.has_cookies}
        />
        <DetailRow
          icon={Cookie}
          label="Local storage"
          value={profile.has_local_storage ? 'Yes' : 'No'}
          ok={profile.has_local_storage}
        />
        {profile.login_url && (
          <DetailRow icon={ExternalLink} label="Login URL" value={profile.login_url} truncate />
        )}
        {profile.uploaded_from && (
          <DetailRow icon={Link2} label="Uploaded via" value={profile.uploaded_from} />
        )}
      </div>

      {profile.linked_jobs.length > 0 ? (
        <div>
          <p className="text-xs text-gray-500 mb-2">Jobs using this profile</p>
          <ul className="space-y-1.5">
            {profile.linked_jobs.map((j) => (
              <li key={j.id}>
                <Link
                  to={`/dashboard/jobs/${j.id}`}
                  className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-2"
                >
                  {j.name}
                  <span className="text-xs text-gray-500 capitalize">({j.status})</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-amber-500/90">
          Koi job is profile se linked nahi — Job detail me Browser Profile Name = &quot;{profile.profile_name}&quot; set karo.
        </p>
      )}
    </div>
  )
}

function DetailRow({
  icon: Icon,
  label,
  value,
  ok,
  truncate,
}: {
  icon: typeof Clock
  label: string
  value: string
  ok?: boolean
  truncate?: boolean
}) {
  return (
    <div className="flex gap-2 py-2 border-b border-gray-800/80 last:border-0">
      <Icon size={16} className="text-gray-500 shrink-0 mt-0.5" />
      <div className="min-w-0">
        <p className="text-xs text-gray-500">{label}</p>
        <p
          className={clsx(
            'text-gray-200 font-medium',
            truncate && 'truncate',
            ok === true && 'text-green-400',
            ok === false && 'text-red-400',
          )}
        >
          {value}
        </p>
      </div>
    </div>
  )
}

export default function SessionPage() {
  const [profiles, setProfiles] = useState<BrowserProfileStatus[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchProfiles()
    const t = setInterval(() => fetchProfiles(true), 15_000)
    return () => clearInterval(t)
  }, [])

  async function fetchProfiles(silent = false) {
    if (!silent) setLoading(true)
    try {
      const { data } = await api.get('/profiles')
      setProfiles(data)
    } catch {
      if (!silent) toast.error('Failed to load session status')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  const indiamart = profiles.find((p) => p.profile_name === 'indiamart') ?? profiles[0]

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white">IndiaMART Session</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            login.ps1 ke baad yahan dikhega session server par aayi ya nahi
          </p>
        </div>
        <button onClick={() => fetchProfiles()} className="btn-ghost py-1.5 px-3 text-xs">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      <div className="card bg-gray-900/80 border-blue-900/40">
        <h2 className="text-sm font-semibold text-white mb-2">Laptop par login (ek baar)</h2>
        <pre className="text-xs text-gray-400 whitespace-pre-wrap font-mono leading-relaxed">
{`Invoke-WebRequest -Uri "https://raw.githubusercontent.com/devangdadhich02/autoclicker/main/scripts/login_and_upload.ps1" -OutFile "login.ps1"
.\\login.ps1`}
        </pre>
        <p className="text-xs text-gray-500 mt-3">
          SUCCESS ke baad is page par Refresh dabao — &quot;Session received&quot; green dikhega.
        </p>
      </div>

      {loading ? (
        <div className="flex justify-center py-16 text-gray-500">
          <Loader2 size={28} className="animate-spin" />
        </div>
      ) : profiles.length === 0 ? (
        <div className="card text-center py-10">
          <XCircle size={32} className="mx-auto text-gray-600 mb-3" />
          <p className="text-gray-400 text-sm">Abhi koi session upload nahi hui.</p>
          <p className="text-xs text-gray-500 mt-2">Pehle login.ps1 chalao, phir Refresh.</p>
        </div>
      ) : (
        <>
          {indiamart && <ProfileCard profile={indiamart} />}
          {profiles.filter((p) => p !== indiamart).map((p) => (
            <ProfileCard key={p.profile_name} profile={p} />
          ))}
        </>
      )}
    </div>
  )
}
