import { createContext, useContext } from 'react'
import type { User } from './api'

export const AuthContext = createContext<{ user: User; setUser: (user: User) => void; logout: () => Promise<void> } | null>(null)
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('Authentication provider is required.')
  return context
}
