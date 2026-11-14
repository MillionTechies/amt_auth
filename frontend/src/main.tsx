import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from 'react-oidc-context'
import './index.css'
import App from './App.tsx'

const { VITE_KEYCLOAK_URL, VITE_REALM, VITE_CLIENT_ID } = import.meta.env

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider
      authority={`${VITE_KEYCLOAK_URL}/realms/${VITE_REALM}`}
      client_id={VITE_CLIENT_ID}
      // `organization` puts the user's organizations and groups in the token.
      scope="openid profile email organization"
      redirect_uri={window.location.origin}
      post_logout_redirect_uri={window.location.origin}
      // Drop the ?code=...&state=... Keycloak leaves in the URL after login.
      onSigninCallback={() => window.history.replaceState({}, '', window.location.pathname)}
    >
      <App />
    </AuthProvider>
  </StrictMode>,
)
