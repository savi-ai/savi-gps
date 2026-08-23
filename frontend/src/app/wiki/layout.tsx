'use client'

import ProtectedRoute from '@/components/ProtectedRoute'

/** Bare shell for full-page wiki reader (no dashboard sidebar). */
export default function WikiReaderLayout({ children }: { children: React.ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>
}
