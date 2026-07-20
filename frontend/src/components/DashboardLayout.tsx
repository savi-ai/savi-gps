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
        <main className="p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
