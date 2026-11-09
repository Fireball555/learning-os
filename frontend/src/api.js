// The login code lives in sessionStorage: closing the tab logs out, so the next person
// on a shared lab computer never inherits someone else's session.
const KEY = 'los_code'
export const getCode = () => { try { return sessionStorage.getItem(KEY) || '' } catch { return '' } }
export const setCode = (c) => { try { c ? sessionStorage.setItem(KEY, c) : sessionStorage.removeItem(KEY) } catch {} }

export async function api(path, { method = 'GET', body, admin } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (admin) headers['x-admin-token'] = admin
  else if (getCode()) headers['Authorization'] = 'Bearer ' + getCode()
  let r
  try {
    r = await fetch('/api' + path, { method, headers, body: body ? JSON.stringify(body) : undefined })
  } catch {
    const err = new Error('network'); err.status = 0; throw err
  }
  let data = null
  try { data = await r.json() } catch {}
  if (!r.ok) {
    const d = data && data.detail
    const err = new Error(typeof d === 'string' ? d : `HTTP ${r.status}`)
    err.status = r.status
    throw err
  }
  return data
}
