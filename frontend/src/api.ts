/**
 * Typed client for the Document Q&A backend.
 *
 * All requests go through the `/api` prefix, which the Vite dev server proxies
 * to the FastAPI app (see vite.config.ts). That keeps the browser on a single
 * origin, so no backend CORS configuration is required.
 */

const BASE_URL = '/api'

export type DocumentStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

export interface UserPublic {
  id: string
  name: string
  username: string
  email: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: UserPublic
}

export interface DocumentPublic {
  id: string
  filename: string
  status: DocumentStatus
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface SourceReference {
  document_id: string
  chunk_index: number
  content: string
  score: number
}

export interface AskResponse {
  answer: string
  sources: SourceReference[]
  no_match: boolean
}

/** Thrown for any non-2xx response, carrying the backend's `detail` message. */
export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(options.headers)
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...options, headers })
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Is the backend running?')
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response))
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      // FastAPI validation errors: [{ loc, msg, type }, ...]
      return body.detail
        .map((item) => (item as { msg?: string })?.msg ?? 'Invalid value')
        .join(', ')
    }
  } catch {
    // Response had no JSON body; fall through to the status text.
  }
  return response.statusText || `Request failed (${response.status})`
}

export interface RegisterInput {
  name: string
  username: string
  email: string
  password: string
}

export function login(username: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export function register(input: RegisterInput): Promise<UserPublic> {
  return request<UserPublic>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getProfile(token: string): Promise<UserPublic> {
  return request<UserPublic>('/auth/me', {}, token)
}

export function listDocuments(token: string): Promise<DocumentPublic[]> {
  return request<DocumentPublic[]>('/documents', {}, token)
}

export function uploadDocument(token: string, file: File): Promise<DocumentPublic> {
  const form = new FormData()
  form.append('file', file)
  return request<DocumentPublic>('/documents', { method: 'POST', body: form }, token)
}

export function askQuestion(
  token: string,
  query: string,
  topK: number,
): Promise<AskResponse> {
  return request<AskResponse>(
    '/ask',
    { method: 'POST', body: JSON.stringify({ query, top_k: topK }) },
    token,
  )
}
