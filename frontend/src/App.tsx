import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from 'react-oidc-context'
import { api, type Me, type Organization } from './api'

export default function App() {
  const auth = useAuth()

  if (auth.isLoading) return <p>Loading…</p>
  if (auth.error) return <p className="error">Sign-in failed: {auth.error.message}</p>
  if (!auth.isAuthenticated || !auth.user) {
    return (
      <main>
        <h1>A Million Techies</h1>
        <button onClick={() => void auth.signinRedirect()}>Sign in</button>
      </main>
    )
  }

  return (
    <main>
      <h1>A Million Techies</h1>
      <Profile token={auth.user.access_token} />
      <button onClick={() => void auth.signoutRedirect()}>Sign out</button>
    </main>
  )
}

function Profile({ token }: { token: string }) {
  const [me, setMe] = useState<Me>()
  const [error, setError] = useState('')

  useEffect(() => {
    api<Me>(token, '/me/').then(setMe, (e: Error) => setError(e.message))
  }, [token])

  if (error) return <p className="error">Could not load your profile: {error}</p>
  if (!me) return <p>Loading your profile…</p>

  return (
    <>
      <p>
        Signed in as <strong>{me.name ?? me.email ?? me.sub}</strong>
      </p>

      <h2>Your organizations</h2>
      {me.organizations.length === 0 && <p>You are not a member of any organization yet.</p>}
      {me.organizations.map((org) => (
        <section key={org.id}>
          <h3>{org.alias}</h3>
          <ul>
            {org.groups.map((group) => (
              <li key={`${group.kind}/${group.name}`}>
                {group.name}
                {group.kind && ` (${group.kind})`}
              </li>
            ))}
          </ul>
          {org.is_admin && <InviteForm token={token} org={org} />}
        </section>
      ))}

      {me.realm_roles.includes('admin') && <CreateOrganizationForm token={token} />}
    </>
  )
}

function InviteForm({ token, org }: { token: string; org: Organization }) {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      await api(token, `/auth/organizations/${org.id}/invitations/`, { email })
      setStatus(`Invitation sent to ${email}.`)
      setEmail('')
    } catch (e) {
      setStatus((e as Error).message)
    }
  }

  return (
    <form onSubmit={submit}>
      <input
        type="email"
        required
        placeholder="Email to invite"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <button>Invite</button>
      {status && <p>{status}</p>}
    </form>
  )
}

function CreateOrganizationForm({ token }: { token: string }) {
  const [name, setName] = useState('')
  const [status, setStatus] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      const org = await api<{ id: string; name: string }>(token, '/auth/organizations/', { name })
      setStatus(`Created ${org.name}.`)
      setName('')
    } catch (e) {
      setStatus((e as Error).message)
    }
  }

  return (
    <form onSubmit={submit}>
      <h2>New organization</h2>
      <input
        required
        placeholder="Organization name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <button>Create</button>
      {status && <p>{status}</p>}
    </form>
  )
}
