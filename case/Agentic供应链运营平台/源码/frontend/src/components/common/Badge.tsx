import { ReactNode } from 'react'
import styles from './Badge.module.css'
import clsx from 'clsx'

interface BadgeProps {
  children: ReactNode
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info'
  size?: 'sm' | 'md'
  className?: string
}

export function Badge({ children, variant = 'default', size = 'md', className }: BadgeProps) {
  return (
    <span className={clsx(styles.badge, styles[variant], styles[size], className)}>
      {children}
    </span>
  )
}
