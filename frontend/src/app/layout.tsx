import './globals.css'
import { Inter } from 'next/font/google'
import { Providers } from '@/components/Providers'
import { cn } from '@/lib/utils'

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' })

export const metadata = {
  title: 'Savi GPS',
  description: 'Savi GPS Alpha — Build new software, understand existing codebases, and plan modernization.',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning className="h-full">
      <body className={cn(inter.variable, inter.className, 'min-h-full font-sans')}>
        <Providers>
          {children}
        </Providers>
      </body>
    </html>
  )
}

