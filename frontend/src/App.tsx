import { useCallback, useState } from 'react'

import { AskPanel } from './components/AskPanel'
import { AuthForm } from './components/AuthForm'
import { DocumentsPanel } from './components/DocumentsPanel'
import type { UserPublic } from './api'

interface Session {
  token: string
  user: UserPublic
}

function App() {
  // The token lives in memory only: a refresh signs the user out rather than
  // persisting a long-lived credential in localStorage.
  const [session, setSession] = useState<Session | null>(null)

  const handleAuthenticated = useCallback((token: string, user: UserPublic) => {
    setSession({ token, user })
  }, [])

  const handleSignOut = useCallback(() => {
    setSession(null)
  }, [])

  if (!session) {
    return (
      <main className="shell shell--centered">
        <AuthForm onAuthenticated={handleAuthenticated} />
      </main>
    )
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1 className="topbar__title">Document Q&amp;A</h1>
          <p className="muted small">
            {session.user.name} · @{session.user.username}
          </p>
        </div>
        <button type="button" className="button button--ghost" onClick={handleSignOut}>
          Sign out
        </button>
      </header>

      <div className="stack">
        <DocumentsPanel token={session.token} onUnauthorized={handleSignOut} />
        <AskPanel token={session.token} onUnauthorized={handleSignOut} />
      </div>
    </main>
  )
}

export default App
