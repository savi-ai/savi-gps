'use client'

import { useRouter, usePathname } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import { Separator } from '@/components/ui/separator'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  LayoutDashboard,
  FolderKanban,
  LayoutGrid,
  GitBranch,
  Search,
  MessageSquare,
  FileSearch,
  RefreshCw,
  ClipboardList,
  BarChart3,
  Shield,
  FileText,
  Settings,
  ClipboardCheck,
  Settings2,
  LogOut,
  Rocket,
} from 'lucide-react'

interface NavItem {
  id: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  path: string
  permission?: string
  roles?: string[]
  capability?: 'build' | 'intelligence' | 'modernize' | 'portfolio'
}

interface NavGroup {
  title: string
  capability?: 'build' | 'intelligence' | 'modernize' | 'portfolio'
  accentClass?: string
  items: NavItem[]
}

/** Canonical sidebar — Alpha ships only implemented surfaces (ADR-0002 + RELEASE_PLAN). */
const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Overview',
    items: [
      { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/dashboard' },
      {
        id: 'projects',
        label: 'Projects',
        icon: FolderKanban,
        path: '/dashboard/projects',
        capability: 'build',
      },
    ],
  },
  {
    title: 'Intelligence',
    capability: 'intelligence',
    accentClass: 'border-l-violet-500',
    items: [
      {
        id: 'applications',
        label: 'Applications',
        icon: LayoutGrid,
        path: '/dashboard/intelligence/applications',
        permission: 'can_use_intelligence',
      },
      {
        id: 'repositories',
        label: 'Repositories',
        icon: GitBranch,
        path: '/dashboard/intelligence/repositories',
        permission: 'can_use_intelligence',
      },
      {
        id: 'intelligence-search',
        label: 'Search',
        icon: Search,
        path: '/dashboard/intelligence/search',
        permission: 'can_use_intelligence',
      },
      {
        id: 'intelligence-chat',
        label: 'Chat',
        icon: MessageSquare,
        path: '/dashboard/intelligence/chat',
        permission: 'can_use_intelligence',
      },
      {
        id: 'intelligence-specs',
        label: 'Specs & Drift',
        icon: FileSearch,
        path: '/dashboard/intelligence/specs',
        permission: 'can_use_intelligence',
      },
    ],
  },
  {
    title: 'Modernize',
    capability: 'modernize',
    accentClass: 'border-l-amber-500',
    items: [
      {
        id: 'modernize-assessments',
        label: 'Assessments',
        icon: RefreshCw,
        path: '/dashboard/modernize/assessments',
        permission: 'can_manage_modernize',
      },
      {
        id: 'modernize-plans',
        label: 'Active Plans',
        icon: ClipboardList,
        path: '/dashboard/modernize/plans',
        permission: 'can_manage_modernize',
      },
    ],
  },
  {
    title: 'Portfolio',
    capability: 'portfolio',
    accentClass: 'border-l-emerald-500',
    items: [
      {
        id: 'portfolio-health',
        label: 'Health',
        icon: BarChart3,
        path: '/dashboard/portfolio/health',
        permission: 'can_view_portfolio',
      },
    ],
  },
  {
    title: 'Admin',
    items: [
      {
        id: 'admin-policies',
        label: 'Policies',
        icon: Shield,
        path: '/dashboard/admin/policies',
        permission: 'can_manage_policies',
        roles: ['admin'],
      },
      {
        id: 'admin-sops',
        label: 'SOPs',
        icon: FileText,
        path: '/dashboard/admin/sops',
      },
      {
        id: 'admin-wiki-review',
        label: 'Wiki Review',
        icon: ClipboardCheck,
        path: '/dashboard/admin/wiki-review',
        permission: 'can_approve_wiki',
        roles: ['admin', 'architect'],
      },
      {
        id: 'admin-analysis-config',
        label: 'Analysis Config',
        icon: Settings2,
        path: '/dashboard/admin/analysis-config',
        permission: 'can_manage_tenant_config',
        roles: ['admin'],
      },
      {
        id: 'tenant-settings',
        label: 'Tenant Settings',
        icon: Settings,
        path: '/dashboard/admin/tenant-settings',
        permission: 'can_manage_tenant_config',
        roles: ['admin'],
      },
    ],
  },
]

export default function Sidebar() {
  const router = useRouter()
  const pathname = usePathname()
  const { user, hasPermission, hasRole, hasCapability, logout, currentTenant } = useAuth()

  const getRoleDisplayName = (role: string) => {
    const roleMap: Record<string, string> = {
      product_manager: 'Product Manager',
      architect: 'Architect',
      developer: 'Developer',
      qa: 'QA',
      admin: 'Admin',
    }
    return roleMap[role] || role
  }

  const isItemVisible = (item: NavItem) => {
    if (item.capability && !hasCapability(item.capability)) return false
    if (item.permission && !hasPermission(item.permission)) return false
    if (item.roles && !item.roles.some((role) => hasRole(role))) return false
    return true
  }

  const isGroupVisible = (group: NavGroup) => {
    if (group.capability && !hasCapability(group.capability)) return false
    return group.items.some(isItemVisible)
  }

  const handleLogout = () => {
    const tenantSlug = localStorage.getItem('tenant_slug') || 'default'
    logout()
    router.push(`/${tenantSlug}/login`)
  }

  const userInitials =
    user?.full_name?.[0]?.toUpperCase() || user?.username?.[0]?.toUpperCase() || 'U'

  const isNavItemActive = (itemPath: string) => {
    if (!pathname) return false
    if (itemPath === '/dashboard') {
      return pathname === '/dashboard'
    }
    return pathname === itemPath || pathname.startsWith(`${itemPath}/`)
  }

  return (
    <aside
      id="app-sidebar"
      className="fixed inset-y-0 left-0 z-50 flex w-64 -translate-x-full flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-transform duration-200 lg:translate-x-0"
    >
      <div className="flex h-16 items-center gap-3 border-b border-sidebar-border px-5">
        <Link href="/dashboard" className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/20">
            <Rocket className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-semibold leading-tight text-sidebar-foreground">
              Savi GPS
            </span>
            <span className="text-[10px] font-medium uppercase tracking-widest text-sidebar-foreground/60">
              Alpha
            </span>
          </div>
        </Link>
      </div>

      {currentTenant && (
        <div className="px-4 py-2">
          <div className="rounded-md bg-sidebar-accent px-3 py-1.5 text-xs text-sidebar-accent-foreground">
            <span className="text-sidebar-foreground/50">Tenant · </span>
            <span className="font-medium">{currentTenant.name}</span>
          </div>
        </div>
      )}

      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {NAV_GROUPS.filter(isGroupVisible).map((group, groupIdx) => {
          const visibleItems = group.items.filter(isItemVisible)
          if (visibleItems.length === 0) return null

          return (
            <div key={group.title} className={cn(groupIdx > 0 && 'mt-6')}>
              <p
                className={cn(
                  'mb-2 border-l-2 pl-2 text-[10px] font-semibold uppercase tracking-widest text-sidebar-foreground/40',
                  group.accentClass
                )}
              >
                {group.title}
              </p>
              <ul className="space-y-0.5">
                {visibleItems.map((item) => {
                  const isActive = isNavItemActive(item.path)
                  const Icon = item.icon
                  return (
                    <li key={item.id}>
                      <Link
                        href={item.path}
                        className={cn(
                          'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                          isActive
                            ? 'bg-primary text-primary-foreground shadow-sm'
                            : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'
                        )}
                      >
                        <Icon className="h-4 w-4 shrink-0" />
                        {item.label}
                      </Link>
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })}
      </nav>

      <Separator className="bg-sidebar-border" />

      <div className="p-4">
        <div className="flex items-center gap-3 rounded-lg bg-sidebar-accent p-3">
          <Avatar className="h-8 w-8">
            <AvatarFallback className="bg-primary/20 text-xs font-semibold text-primary">
              {userInitials}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-sidebar-foreground">
              {user?.full_name || user?.username}
            </p>
            <p className="truncate text-xs text-sidebar-foreground/50">
              {user?.roles.map(getRoleDisplayName).join(', ')}
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="mt-2 w-full justify-start gap-2 text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground"
          onClick={handleLogout}
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </Button>
      </div>
    </aside>
  )
}
