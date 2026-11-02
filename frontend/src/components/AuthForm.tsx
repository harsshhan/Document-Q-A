import { useState } from 'react'

import { login, register, ApiError } from '../api'
import type { UserPublic } from '../api'

interface AuthFormProps {
  onAuthenticated: (token: string, user: UserPublic) => void
}

type Mode = 'login' | 'register'

export function AuthForm({ onAuthenticated }: AuthFormProps) {
  const [mode, setMode] = useState<Mode>('login')
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setNotice(null)
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setNotice(null)
    setBusy(true)

    try {
      if (mode === 'register') {
        await register({ name, username, email, password })
        setNotice('Account created. Signing you in…')
      }
      const session = await login(username, password)
      onAuthenticated(session.access_token, session.user)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <header className="auth__intro">
        <h1>Document Q&amp;A</h1>
        <p>Upload a PDF, then ask questions answered only from its contents.</p>
      </header>

      <div className="card">
        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            className={mode === 'login' ? 'tab tab--active' : 'tab'}
            onClick={() => switchMode('login')}
          >
            Log in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            className={mode === 'register' ? 'tab tab--active' : 'tab'}
            onClick={() => switchMode('register')}
          >
            Register
          </button>
        </div>

        <form onSubmit={handleSubmit} className="form">
          {mode === 'register' && (
            <label className="field">
              <span>Name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                maxLength={255}
                autoComplete="name"
              />
            </label>
          )}

          <label className="field">
            <span>Username</span>
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
              minLength={mode === 'register' ? 3 : 1}
              maxLength={64}
              autoComplete="username"
            />
          </label>

          {mode === 'register' && (
            <label className="field">
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                autoComplete="email"
              />
            </label>
          )}

          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={mode === 'register' ? 8 : 1}
              maxLength={128}
              autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            />
            {mode === 'register' && <small>At least 8 characters.</small>}
          </label>

          {error && <p className="alert alert--error">{error}</p>}
          {notice && <p className="alert">{notice}</p>}

          <button type="submit" className="button" disabled={busy}>
            {busy ? 'Working…' : mode === 'login' ? 'Log in' : 'Create account'}
          </button>
        </form>
      </div>
    </div>
  )
}
