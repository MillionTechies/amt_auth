export type Group = { name: string; kind: string | null }

export type Organization = { id: string; alias: string; is_admin: boolean; groups: Group[] }

export type Me = {
  sub: string
  email: string | null
  name: string | null
  realm_roles: string[]
  organizations: Organization[]
}

/** Call the Django backend with the Keycloak access token. */
export async function api<T>(token: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  if (!response.ok) throw new Error(`${response.status}: ${text || response.statusText}`)
  return (text ? JSON.parse(text) : undefined) as T
}
