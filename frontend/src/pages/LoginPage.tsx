import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Zap, Eye, EyeOff, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../lib/api'
import { useAuthStore } from '../store/authStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const { setTokens, setUser } = useAuthStore()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      const { data } = await api.post('/auth/login', { email, password })
      setTokens(data.access_token, data.refresh_token)
      const me = await api.get('/auth/me', {
        headers: { Authorization: `Bearer ${data.access_token}` },
      })
      setUser(me.data)
      toast.success('Welcome back!')
      navigate('/dashboard')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex items-center justify-center gap-3 mb-8">
          <div className="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-600/30">
            <Zap size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Velora</h1>
            <p className="text-xs text-gray-500">Auto Clicker Platform</p>
          </div>
        </div>

        <div className="card">
          <h2 className="text-base font-semibold text-white mb-1">Sign in</h2>
          <p className="text-xs text-gray-500 mb-6">Control Panel — Team Velora</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="label">Email address</label>
              <input
                type="email"
                className="input"
                placeholder="admin@velora.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div>
              <label className="label">Password</label>
              <div className="relative">
                <input
                  type={showPass ? 'text' : 'password'}
                  className="input pr-10"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPass((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                >
                  {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full justify-center py-2.5"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : null}
              {loading ? 'Signing in...' : 'Sign in'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-600 mt-6">
          © {new Date().getFullYear()} Team Velora. All rights reserved.
        </p>
      </div>
    </div>
  )
}
