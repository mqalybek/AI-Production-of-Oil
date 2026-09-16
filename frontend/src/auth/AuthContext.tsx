import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { clearToken, getToken, setToken } from '../api/client'
import { login as loginRequest } from '../api/endpoints'

interface AuthState {
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(() => getToken() !== null)

  const value = useMemo<AuthState>(
    () => ({
      isAuthenticated,
      login: async (username: string, password: string) => {
        const { access_token } = await loginRequest(username, password)
        setToken(access_token)
        setIsAuthenticated(true)
      },
      logout: () => {
        clearToken()
        setIsAuthenticated(false)
      },
    }),
    [isAuthenticated],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth должен вызываться внутри AuthProvider')
  return ctx
}
