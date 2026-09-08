import { ReactNode } from 'react'
import styles from './Card.module.css'
import clsx from 'clsx'

interface CardProps {
  children: ReactNode
  className?: string
  variant?: 'default' | 'highlighted' | 'glass'
  padding?: 'none' | 'sm' | 'md' | 'lg'
}

export function Card({ children, className, variant = 'default', padding = 'md' }: CardProps) {
  return (
    <div className={clsx(styles.card, styles[variant], styles[`padding-${padding}`], className)}>
      {children}
    </div>
  )
}
