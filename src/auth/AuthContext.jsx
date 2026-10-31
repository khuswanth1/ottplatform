import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, getProfileId, setCsrf, setOnProfileLocked, setProfileId } from '../api/client'

const Ctx = createContext(null)
export const AuthContext = Ctx // exported so the design gallery can supply a made-up signed-in state
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }) {
  const qc = useQueryClient()
  const [profileId, setPid] = useState(getProfileId())

  const me = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        const r = await api('/auth/me')
        setCsrf(r.csrf_token)
        return r.user
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  })
  const user = me.data ?? null

  const profiles = useQuery({
    queryKey: ['profiles', user?.id],
    queryFn: () => api('/profiles'),
    enabled: !!user,
    staleTime: 5 * 60_000,
  })

  // drop a stale/foreign profile id (e.g. account switched on this browser)
  useEffect(() => {
    if (profiles.data && profileId && !profiles.data.some((p) => p.id === profileId)) {
      setProfileId(''); setPid('')
    }
  }, [profiles.data, profileId])

  useEffect(() => {
    setOnProfileLocked(() => { setProfileId(''); setPid('') })
    return () => setOnProfileLocked(null)
  }, [])

  const selectProfile = useCallback((id) => {
    setProfileId(id); setPid(id)
    qc.invalidateQueries({ predicate: (q) => !['me', 'profiles'].includes(q.queryKey[0]) })
  }, [qc])

  const login = useCallback(async (email, password) => {
    const r = await api('/auth/login', { method: 'POST', body: { email, password } })
    setCsrf(r.csrf_token)
    qc.setQueryData(['me'], r.user)
    return r.user
  }, [qc])

  const logout = useCallback(async () => {
    try { await api('/auth/logout', { method: 'POST' }) } finally {
      setCsrf(''); setProfileId(''); setPid('')
      qc.clear()
      qc.setQueryData(['me'], null)
    }
  }, [qc])

  const activeProfile = profiles.data?.find((p) => p.id === profileId) ?? null
  const value = useMemo(() => ({
    user, loading: me.isLoading, profiles: profiles.data ?? [], profilesLoading: profiles.isLoading,
    activeProfile, profileId, selectProfile, login, logout, isAdmin: user?.role === 'admin',
  }), [user, me.isLoading, profiles.data, profiles.isLoading, activeProfile, profileId, selectProfile, login, logout])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
