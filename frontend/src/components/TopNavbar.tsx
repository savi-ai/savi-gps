'use client'

import { useRouter, usePathname } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { useTheme } from '@/contexts/ThemeContext'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Menu, Moon, Sun, LogOut, ChevronRight } from 'lucide-react'

const SEGMENT_TITLES: Record<string, string> = {
  '': 'Dashboard',
  projects: 'Projects',
  new: 'New',
  intelligence: 'Intelligence',
  applications: 'Applications',
  repositories: 'Repositories',
  search: 'Search',
  chat: 'Chat',
  specs: 'Specs & Drift',
  modernize: 'Modernize',
  assessments: 'Assessments',
  plans: 'Active Plans',
  playbooks: 'Playbooks',
  'fleet-operations': 'Fleet Operations',
  portfolio: 'Portfolio',
  health: 'Health',
  risk: 'Risk Posture',
  modernization: 'Modernization',
  cost: 'Cost & Spend',
  trends: 'Trends',
  admin: 'Admin',
  policies: 'Policies',
  sops: 'SOPs',
  'wiki-review': 'Wiki Review',
  'analysis-config': 'Analysis Config',
  'tenant-settings': 'Tenant Settings',
  runs: 'Workflow Run',
  logs: 'Live Monitor',
  deploy: 'Deployment',
}

function getPageTitle(pathname: string | null): string {
  if (!pathname) return 'Dashboard'
  const segments = pathname.replace('/dashboard', '').split('/').filter(Boolean)
  if (segments.length === 0) return 'Dashboard'
  const last = segments[segments.length - 1]
  if (last === 'new') return 'New'
  if (/^[0-9a-f-]{36}$/i.test(last) || segments.includes('runs')) {
    if (segments[0] === 'projects') return 'Project'
    if (segments[0] === 'intelligence' && segments[1] === 'applications') return 'Application'
    if (segments[0] === 'intelligence' && segments[1] === 'repositories') return 'Repository'
    if (segments[0] === 'modernize' && segments[1] === 'plans') return 'Plan'
  }
  return SEGMENT_TITLES[last] || SEGMENT_TITLES[segments[0]] || 'Dashboard'
}

function getBreadcrumbs(pathname: string | null): { label: string; href?: string }[] {
  if (!pathname || pathname === '/dashboard') return [{ label: 'Dashboard' }]

  const crumbs: { label: string; href?: string }[] = [{ label: 'Dashboard', href: '/dashboard' }]
  const parts = pathname.replace('/dashboard/', '').split('/').filter(Boolean)

  if (parts[0] === 'projects') {
    crumbs.push({ label: 'Projects', href: '/dashboard/projects' })
    if (parts[1] === 'new') crumbs.push({ label: 'New Project' })
    else if (parts.length > 1) crumbs.push({ label: 'Project' })
    return crumbs
  }

  if (parts[0] === 'intelligence') {
    crumbs.push({ label: 'Intelligence', href: '/dashboard/intelligence/applications' })
    if (parts[1] === 'applications') {
      crumbs.push({ label: 'Applications', href: '/dashboard/intelligence/applications' })
      if (parts[2] && parts[2] !== 'new') crumbs.push({ label: 'Application' })
      else if (parts[2] === 'new') crumbs.push({ label: 'New Application' })
    } else if (parts[1]) {
      crumbs.push({ label: SEGMENT_TITLES[parts[1]] || parts[1] })
    }
    return crumbs
  }

  if (parts[0] === 'modernize') {
    crumbs.push({ label: 'Modernize', href: '/dashboard/modernize/assessments' })
    if (parts[1]) crumbs.push({ label: SEGMENT_TITLES[parts[1]] || parts[1] })
    return crumbs
  }

  if (parts[0] === 'portfolio') {
    crumbs.push({ label: 'Portfolio', href: '/dashboard/portfolio/health' })
    if (parts[1]) crumbs.push({ label: SEGMENT_TITLES[parts[1]] || parts[1] })
    return crumbs
  }

  if (parts[0] === 'admin') {
    crumbs.push({ label: 'Admin', href: '/dashboard/admin/policies' })
    if (parts[1]) crumbs.push({ label: SEGMENT_TITLES[parts[1]] || parts[1] })
    return crumbs
  }

  crumbs.push({ label: getPageTitle(pathname) })
  return crumbs
}

export default function TopNavbar() {
  const router = useRouter()
  const pathname = usePathname()
  const { user, logout } = useAuth()
  const { theme, toggleTheme } = useTheme()

  const breadcrumbs = getBreadcrumbs(pathname)
  const userInitials =
    user?.full_name?.[0]?.toUpperCase() || user?.username?.[0]?.toUpperCase() || 'U'

  const handleLogout = () => {
    const tenantSlug = localStorage.getItem('tenant_slug') || 'default'
    logout()
    router.push(`/${tenantSlug}/login`)
  }

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

  return (
    <header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b bg-background/95 px-6 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          onClick={() => document.getElementById('app-sidebar')?.classList.toggle('open')}
          aria-label="Toggle menu"
        >
          <Menu className="h-5 w-5" />
        </Button>

        <nav className="flex items-center gap-1 text-sm">
          {breadcrumbs.map((crumb, idx) => (
            <div key={idx} className="flex items-center gap-1">
              {idx > 0 && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
              {crumb.href ? (
                <button
                  onClick={() => router.push(crumb.href!)}
                  className="text-muted-foreground transition-colors hover:text-foreground"
                >
                  {crumb.label}
                </button>
              ) : (
                <span className="font-medium text-foreground">{crumb.label}</span>
              )}
            </div>
          ))}
        </nav>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          title={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          aria-label="Toggle theme"
        >
          {theme === 'light' ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="relative h-9 gap-2 px-2">
              <Avatar className="h-7 w-7">
                <AvatarFallback className="bg-primary/10 text-xs font-semibold text-primary">
                  {userInitials}
                </AvatarFallback>
              </Avatar>
              <span className="hidden text-sm font-medium md:inline-block">
                {user?.full_name || user?.username}
              </span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <div className="px-2 py-1.5">
              <p className="text-sm font-medium">{user?.full_name || user?.username}</p>
              <p className="text-xs text-muted-foreground">
                {user?.roles.map(getRoleDisplayName).join(', ')}
              </p>
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout} className="text-destructive focus:text-destructive">
              <LogOut className="mr-2 h-4 w-4" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
