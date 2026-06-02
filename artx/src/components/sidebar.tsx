import { useState } from 'react'
import { cn } from '@/lib/utils'
import {
  LayoutDashboard,
  FilePlus,
  GitBranch,
  CheckSquare,
  Home,
  Building2,
  MessageSquare,
  Activity,
  ChevronLeft,
  ChevronRight,
  LogOut,
  Shield,
  Users,
  BrainCircuit,
} from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'

const navItems = [
  { icon: LayoutDashboard, label: 'Dashboard', path: '/' },
  { icon: FilePlus, label: 'New Referral', path: '/referral' },
  { icon: GitBranch, label: 'Workflows', path: '/workflow' },
  { icon: CheckSquare, label: 'Approvals', path: '/approvals' },
  { icon: Home, label: 'Placements', path: '/placements' },
  { icon: Building2, label: 'Families', path: '/families' },
  { icon: Users, label: 'Children', path: '/children' },
  { icon: BrainCircuit, label: 'Digital Twin', path: '/twin' },
  { icon: Shield, label: 'Fairness', path: '/fairness' },
  { icon: MessageSquare, label: 'AI Assistant', path: '/chat' },
  { icon: Activity, label: 'Monitoring', path: '/monitoring' },
]

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 h-screen z-40 flex flex-col border-r border-border bg-background/80 backdrop-blur-xl transition-all duration-300',
        collapsed ? 'w-16' : 'w-56'
      )}
    >
      <div className={cn('flex items-center gap-3 px-4 h-16 border-b border-border shrink-0', collapsed && 'justify-center px-0')}>
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-secondary flex items-center justify-center shrink-0">
          <span className="text-white font-bold text-sm">A</span>
        </div>
        {!collapsed && (
          <div className="flex flex-col">
            <span className="text-sm font-bold text-foreground">Artifex</span>
            <span className="text-[10px] text-muted-foreground">Orchestration Platform</span>
          </div>
        )}
      </div>

      <nav className="flex-1 py-4 px-2 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = item.path === '/' ? location.pathname === '/' : location.pathname.startsWith(item.path)
          const Icon = item.icon
          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-200 group',
                collapsed && 'justify-center px-2',
                isActive
                  ? 'bg-primary/10 text-primary border border-primary/20'
                  : 'text-muted-foreground hover:text-foreground hover:bg-glass-hover border border-transparent'
              )}
              title={collapsed ? item.label : undefined}
            >
              <Icon size={18} className={cn('shrink-0', isActive && 'text-primary')} />
              {!collapsed && <span>{item.label}</span>}
              {!collapsed && isActive && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-primary" />
              )}
            </Link>
          )
        })}
      </nav>

      {/* User info + logout */}
      <div className="px-2 pb-2 border-t border-border pt-2 space-y-1">
        {!collapsed && user && (
          <div className="px-3 py-2">
            <p className="text-xs text-foreground font-medium truncate">{user.user_id}</p>
            <p className="text-[10px] text-muted-foreground capitalize">{user.role}</p>
          </div>
        )}
        <button
          onClick={handleLogout}
          className={cn(
            'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm w-full transition-all duration-200',
            'text-muted-foreground hover:text-destructive hover:bg-destructive/10 border border-transparent',
            collapsed && 'justify-center px-2'
          )}
          title={collapsed ? 'Sign out' : undefined}
        >
          <LogOut size={18} className="shrink-0" />
          {!collapsed && <span>Sign out</span>}
        </button>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center justify-center w-full h-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-glass-hover transition-all cursor-pointer"
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>
    </aside>
  )
}
