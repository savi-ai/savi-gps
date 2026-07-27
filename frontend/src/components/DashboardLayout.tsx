'use client'

import { ReactNode } from 'react'
import Sidebar from './Sidebar'
import TopNavbar from './TopNavbar'

interface DashboardLayoutProps {
  children: ReactNode
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <div className="lg:pl-64">
        <TopNavbar />
        <main className="min-w-0 overflow-x-auto p-4 sm:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
