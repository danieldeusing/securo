import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { auth, info } from '@/lib/api'
import type { User } from '@/types'

interface LoginResult {
  requires_2fa: boolean
  temp_token?: string
  available_methods?: Array<'totp' | 'passkey'>
}

interface AuthContextType {
  user: User | null
  token: string | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<LoginResult>
  verify2fa: (tempToken: string, code: string) => Promise<void>
  loginWithToken: (accessToken: string) => void
  register: (email: string, password: string, preferences?: Record<string, string>) => Promise<void>
  updateUser: (user: User) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const [isLoading, setIsLoading] = useState(true)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (token) {
      auth.me()
        .then(setUser)
        .catch(() => {
          localStorage.removeItem('token')
          setToken(null)
        })
        .finally(() => setIsLoading(false))
    } else {
      // Demo mode: mint a JWT for the seeded demo user so visitors land
      // straight on the dashboard. /api/info reports demo=true only when
      // DEMO_MODE is on; the endpoint 404s otherwise so this is a no-op
      // for self-hosted users.
      info.get()
        .then(({ features }) => {
          if (!features?.demo) {
            setUser(null)
            setIsLoading(false)
            return
          }
          return info.demoLogin().then(({ access_token }) => {
            localStorage.setItem('token', access_token)
            setToken(access_token)
          })
        })
        .catch(() => {
          setUser(null)
          setIsLoading(false)
        })
    }
  }, [token])

  // Sync token across tabs via storage events
  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'token') {
        setToken(e.newValue)
      }
    }
    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [])

  const login = useCallback(async (email: string, password: string): Promise<LoginResult> => {
    const data = await auth.login(email, password)

    if (data.requires_2fa) {
      return { requires_2fa: true, temp_token: data.temp_token, available_methods: data.available_methods }
    }

    const accessToken = data.access_token
    localStorage.setItem('token', accessToken)
    setToken(accessToken)
    const me = await auth.me()
    setUser(me)
    return { requires_2fa: false }
  }, [])

  const verify2fa = useCallback(async (tempToken: string, code: string) => {
    const data = await auth.verify2fa(tempToken, code)
    localStorage.setItem('token', data.access_token)
    setToken(data.access_token)
    const me = await auth.me()
    setUser(me)
  }, [])

  const loginWithToken = useCallback((accessToken: string) => {
    localStorage.setItem('token', accessToken)
    setToken(accessToken)
    auth.me().then(setUser).catch(() => {})
  }, [])

  const updateUser = useCallback((updatedUser: User) => {
    setUser(updatedUser)
  }, [])

  const register = useCallback(async (email: string, password: string, preferences?: Record<string, string>) => {
    await auth.register(email, password, preferences)
    await login(email, password)
  }, [login])

  const logout = useCallback(() => {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
    queryClient.clear()
  }, [queryClient])

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, verify2fa, loginWithToken, register, updateUser, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
