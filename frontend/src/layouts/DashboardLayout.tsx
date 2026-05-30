import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Briefcase, ScrollText, Users, Settings,
  LogOut, Zap, Cookie,
} from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import toast from 'react-hot-toast'

const navItems = [
  { to: '/dashboard', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/dashboard/session', label: 'Seller Session', icon: Cookie },
  { to: '/dashboard/jobs', label: 'Automation Jobs', icon: Briefcase },
  { to: '/dashboard/logs', label: 'Event Logs', icon: ScrollText },
  { to: '/dashboard/users', label: 'Users', icon: Users, adminOnly: true },
  { to: '/dashboard/settings', label: 'Settings', icon: Settings },
]

export default function DashboardLayout() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    toast.success('Logged out')
    navigate('/login')
  }

  return (
    <div className="flex h-screen bg-gray-950 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-60 flex flex-col bg-gray-900 border-r border-gray-800 shrink-0">
        {/* Brand */}
        <div className="flex items-center gap-3 px-5 py-5 border-b border-gray-800">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
            <Zap size={16} className="text-white" />
          </div>
          <div>
            <p className="text-sm font-semibold text-white">Velora</p>
            <p className="text-xs text-gray-500">Auto Clicker</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {navItems.map((item) => {
            if (item.adminOnly && user?.role !== 'admin') return null
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-blue-600/20 text-blue-400 font-medium'
                      : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                  }`
                }
              >
                <item.icon size={16} />
                {item.label}
              </NavLink>
            )
          })}
        </nav>

        {/* User info */}
        <div className="border-t border-gray-800 px-4 py-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded-full bg-blue-700 flex items-center justify-center text-xs font-bold text-white uppercase">
              {user?.full_name?.[0] ?? 'U'}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-medium text-gray-200 truncate">{user?.full_name}</p>
              <p className="text-xs text-gray-500 truncate capitalize">{user?.role}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-2 w-full px-3 py-2 text-xs text-gray-400 hover:text-red-400 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <LogOut size={13} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
