import { useState } from 'react'
import { Save, Loader2, KeyRound } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../lib/api'

export default function SettingsPage() {
  const [oldPass, setOldPass] = useState('')
  const [newPass, setNewPass] = useState('')
  const [confirmPass, setConfirmPass] = useState('')
  const [saving, setSaving] = useState(false)

  async function changePassword(e: React.FormEvent) {
    e.preventDefault()
    if (newPass !== confirmPass) { toast.error('Passwords do not match'); return }
    if (newPass.length < 8) { toast.error('Password must be at least 8 characters'); return }
    setSaving(true)
    try {
      await api.post('/auth/change-password', { current_password: oldPass, new_password: newPass })
      toast.success('Password updated successfully')
      setOldPass(''); setNewPass(''); setConfirmPass('')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Failed to update password')
    } finally { setSaving(false) }
  }

  return (
    <div className="p-6 space-y-6 max-w-xl">
      <div>
        <h1 className="text-xl font-bold text-white">Settings</h1>
        <p className="text-sm text-gray-500 mt-0.5">Manage your account preferences</p>
      </div>

      <div className="card space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <KeyRound size={15} className="text-blue-400" />
          <h2 className="text-sm font-semibold text-white">Change Password</h2>
        </div>
        <form onSubmit={changePassword} className="space-y-3">
          <div>
            <label className="label">Current Password</label>
            <input type="password" className="input" value={oldPass} onChange={e => setOldPass(e.target.value)} required />
          </div>
          <div>
            <label className="label">New Password</label>
            <input type="password" className="input" value={newPass} onChange={e => setNewPass(e.target.value)} required minLength={8} />
          </div>
          <div>
            <label className="label">Confirm New Password</label>
            <input type="password" className="input" value={confirmPass} onChange={e => setConfirmPass(e.target.value)} required minLength={8} />
          </div>
          <button type="submit" disabled={saving} className="btn-primary">
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            Update Password
          </button>
        </form>
      </div>

      <div className="card">
        <h2 className="text-sm font-semibold text-white mb-3">System Information</h2>
        <dl className="space-y-2 text-xs">
          {[
            ['Platform', 'Velora Auto Clicker v1.0.0'],
            ['Backend', 'FastAPI + Python 3.13'],
            ['Automation', 'Playwright (Chromium)'],
            ['Database', 'PostgreSQL / SQLite'],
            ['Frontend', 'React 18 + TailwindCSS'],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between py-1.5 border-b border-gray-800 last:border-0">
              <dt className="text-gray-500">{k}</dt>
              <dd className="text-gray-300 font-medium">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
