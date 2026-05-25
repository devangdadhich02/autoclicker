import { useEffect, useState } from 'react'
import { Plus, UserCheck, UserX, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../lib/api'
import type { User, UserRole } from '../types'

const ROLES: UserRole[] = ['admin', 'operator', 'viewer']

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<UserRole>('operator')
  const [password, setPassword] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => { fetchUsers() }, [])

  async function fetchUsers() {
    setLoading(true)
    try { const { data } = await api.get('/users'); setUsers(data) }
    catch { toast.error('Failed to load users') }
    finally { setLoading(false) }
  }

  async function createUser(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      await api.post('/users', { email, full_name: fullName, role, password })
      toast.success('User created')
      setEmail(''); setFullName(''); setPassword(''); setShowForm(false)
      fetchUsers()
    } catch (err: any) { toast.error(err?.response?.data?.detail ?? 'Failed') }
    finally { setSaving(false) }
  }

  async function toggleActive(user: User) {
    try {
      await api.patch(`/users/${user.id}`, { is_active: !user.is_active })
      toast.success(`User ${user.is_active ? 'deactivated' : 'activated'}`)
      fetchUsers()
    } catch { toast.error('Failed to update user') }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">User Management</h1>
          <p className="text-sm text-gray-500 mt-0.5">{users.length} users registered</p>
        </div>
        <button onClick={() => setShowForm(v => !v)} className="btn-primary">
          <Plus size={14} /> New User
        </button>
      </div>

      {showForm && (
        <form onSubmit={createUser} className="card space-y-3">
          <h2 className="text-sm font-semibold text-white">Create User</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div><label className="label">Full Name</label><input className="input" value={fullName} onChange={e => setFullName(e.target.value)} required /></div>
            <div><label className="label">Email</label><input type="email" className="input" value={email} onChange={e => setEmail(e.target.value)} required /></div>
            <div>
              <label className="label">Role</label>
              <select className="input" value={role} onChange={e => setRole(e.target.value as UserRole)}>
                {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div><label className="label">Password</label><input type="password" className="input" value={password} onChange={e => setPassword(e.target.value)} required /></div>
          </div>
          <div className="flex gap-2 pt-1">
            <button type="button" onClick={() => setShowForm(false)} className="btn-ghost">Cancel</button>
            <button type="submit" disabled={saving} className="btn-primary">
              {saving ? <Loader2 size={13} className="animate-spin" /> : null} Create
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-40"><Loader2 size={22} className="animate-spin text-gray-500" /></div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs">
                <th className="px-5 py-3 text-left font-medium">Name</th>
                <th className="px-5 py-3 text-left font-medium">Email</th>
                <th className="px-5 py-3 text-left font-medium">Role</th>
                <th className="px-5 py-3 text-left font-medium">Status</th>
                <th className="px-5 py-3 text-left font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map(user => (
                <tr key={user.id} className="border-b border-gray-800/50 hover:bg-gray-800/20 transition-colors">
                  <td className="px-5 py-3 text-gray-200">{user.full_name}</td>
                  <td className="px-5 py-3 text-gray-400">{user.email}</td>
                  <td className="px-5 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full border capitalize
                      ${user.role === 'admin' ? 'bg-purple-900/40 text-purple-300 border-purple-800'
                        : user.role === 'operator' ? 'bg-blue-900/40 text-blue-300 border-blue-800'
                        : 'bg-gray-800 text-gray-400 border-gray-700'}`}>
                      {user.role}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    {user.is_active
                      ? <span className="badge-running">Active</span>
                      : <span className="badge-stopped">Inactive</span>}
                  </td>
                  <td className="px-5 py-3">
                    <button onClick={() => toggleActive(user)}
                      className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg transition-colors
                        ${user.is_active ? 'bg-red-900/30 text-red-400 hover:bg-red-900/50' : 'bg-green-900/30 text-green-400 hover:bg-green-900/50'}`}>
                      {user.is_active ? <><UserX size={12} /> Deactivate</> : <><UserCheck size={12} /> Activate</>}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
