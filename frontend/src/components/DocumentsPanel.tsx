import { useEffect, useRef, useState } from 'react'

import { ApiError, listDocuments, uploadDocument } from '../api'
import type { DocumentPublic } from '../api'

interface DocumentsPanelProps {
  token: string
  onUnauthorized: () => void
}

const STATUS_LABEL: Record<DocumentPublic['status'], string> = {
  PENDING: 'Pending',
  PROCESSING: 'Processing',
  COMPLETED: 'Ready',
  FAILED: 'Failed',
}

export function DocumentsPanel({ token, onUnauthorized }: DocumentsPanelProps) {
  const [documents, setDocuments] = useState<DocumentPublic[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let active = true
    listDocuments(token)
      .then((docs) => {
        if (active) setDocuments(docs)
      })
      .catch((err: unknown) => {
        if (!active) return
        if (err instanceof ApiError && err.status === 401) return onUnauthorized()
        setError(err instanceof ApiError ? err.message : 'Could not load documents.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [token, onUnauthorized])

  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return

    setBusy(true)
    setError(null)
    try {
      const created = await uploadDocument(token, file)
      setDocuments((current) => [created, ...current])
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized()
      setError(err instanceof ApiError ? err.message : 'Upload failed.')
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <section className="card">
      <div className="card__head">
        <h2>Documents</h2>
        <label className="button button--ghost">
          {busy ? 'Uploading…' : 'Upload PDF'}
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            onChange={handleFile}
            disabled={busy}
            hidden
          />
        </label>
      </div>

      {error && <p className="alert alert--error">{error}</p>}

      {loading ? (
        <p className="muted">Loading…</p>
      ) : documents.length === 0 ? (
        <p className="muted">No documents yet. Upload a PDF to get started.</p>
      ) : (
        <ul className="list">
          {documents.map((doc) => (
            <li key={doc.id} className="list__row">
              <div className="list__main">
                <span className="list__title">{doc.filename}</span>
                <span className="muted small">{formatDate(doc.created_at)}</span>
              </div>
              <span className={`badge badge--${doc.status.toLowerCase()}`}>
                {STATUS_LABEL[doc.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
