import { useState } from 'react'

import { ApiError, askQuestion } from '../api'
import type { AskResponse } from '../api'

interface AskPanelProps {
  token: string
  onUnauthorized: () => void
}

export function AskPanel({ token, onUnauthorized }: AskPanelProps) {
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(3)
  const [result, setResult] = useState<AskResponse | null>(null)
  const [askedQuery, setAskedQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) return

    setBusy(true)
    setError(null)
    try {
      const response = await askQuestion(token, trimmed, topK)
      setResult(response)
      setAskedQuery(trimmed)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized()
      setResult(null)
      setError(err instanceof ApiError ? err.message : 'Could not get an answer.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <div className="card__head">
        <h2>Ask</h2>
        <label className="inline-field">
          <span>Sources</span>
          <select value={topK} onChange={(event) => setTopK(Number(event.target.value))}>
            {[1, 3, 5, 10].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </div>

      <form onSubmit={handleSubmit} className="form">
        <textarea
          className="textarea"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Ask something about your documents…"
          rows={3}
          maxLength={2000}
          required
        />
        <button type="submit" className="button" disabled={busy || !query.trim()}>
          {busy ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      {error && <p className="alert alert--error">{error}</p>}

      {result && (
        <div className="answer">
          <p className="muted small">Your question: {askedQuery}</p>
          <p className={result.no_match ? 'answer__text answer__text--empty' : 'answer__text'}>
            {result.answer}
          </p>

          {result.sources.length > 0 && (
            <>
              <h3 className="answer__heading">Sources</h3>
              <ul className="list">
                {result.sources.map((source) => (
                  <li key={`${source.document_id}-${source.chunk_index}`} className="source">
                    <div className="source__head">
                      <span className="muted small">
                        chunk {source.chunk_index} · {source.document_id.slice(0, 8)}
                      </span>
                      <span className="muted small">score {source.score.toFixed(2)}</span>
                    </div>
                    <p className="source__text">{source.content}</p>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  )
}
