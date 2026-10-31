import axios from 'axios'

const BASE = (import.meta.env?.VITE_API_BASE || '') + '/api/v1'

let csrfToken = ''
// The API says a PIN-locked profile is not open in this session; AuthProvider drops the stored profile so the picker shows.
let onProfileLocked = null
export const setOnProfileLocked = (f) => { onProfileLocked = f }

export const setCsrf = (t) => { csrfToken = t || '' }

const PROFILE_KEY = 'ott.profile'
export const getProfileId = () => { try { return localStorage.getItem(PROFILE_KEY) || '' } catch { return '' } }
export const setProfileId = (id) => { try { id ? localStorage.setItem(PROFILE_KEY, id) : localStorage.removeItem(PROFILE_KEY) } catch { /* private mode */ } }

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : detail?.message || 'Request failed')
    this.status = status
    this.code = typeof detail === 'object' ? detail?.code : undefined
    this.detail = detail
  }
}

/** Normalises FastAPI error bodies (string, {code,message}, or validation arrays) into one message. */
export function parseDetail(body) {
  const d = body?.detail
  if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`).join('; ')
  return d ?? 'Something went wrong. Please try again.'
}

export function buildQuery(params = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') q.set(k, v) })
  const s = q.toString()
  return s ? `?${s}` : ''
}

const http = axios.create({ baseURL: BASE, withCredentials: true, timeout: 20_000 })

function buildHeaders(hasBody) {
  const headers = {}
  if (hasBody) headers['Content-Type'] = 'application/json'
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken
  const pid = getProfileId()
  if (pid) headers['X-Profile-Id'] = pid
  return headers
}

// keepalive requests (progress/session cleanup while the page unloads) must use fetch:
// XHR is cancelled on unload and sendBeacon cannot carry the CSRF header.
async function fetchKeepalive(path, { method, body, params }) {
  const res = await fetch(BASE + path + buildQuery(params), {
    method, headers: buildHeaders(body !== undefined), credentials: 'include', keepalive: true,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const data = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, parseDetail(data))
  return data
}

export async function api(path, { method = 'GET', body, params, signal, keepalive } = {}) {
  try {
    if (keepalive) return await fetchKeepalive(path, { method, body, params })
    const res = await http.request({
      url: path, method, params: params ? Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')) : undefined,
      data: body, signal, headers: buildHeaders(body !== undefined),
    })
    return res.status === 204 ? null : res.data
  } catch (e) {
    if (e instanceof ApiError) throw e
    if (axios.isCancel(e)) throw e // aborted by TanStack Query / unmount: not an error to surface
    if (e.response) {
      if (e.response.status === 403 && e.response.data?.detail?.code === 'profile_locked') onProfileLocked?.()
      throw new ApiError(e.response.status, e.response.data?.detail?.code ? e.response.data.detail : parseDetail(e.response.data))
    }
    throw new ApiError(0, 'Cannot reach the server. Check your connection.')
  }
}
