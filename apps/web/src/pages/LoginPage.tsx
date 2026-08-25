import { useState } from 'react'
import type { MeResponse } from '../api'
import { fetchMe, login } from '../api'

export default function LoginPage({ onLogin }: { onLogin: (me: MeResponse | null) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      onLogin(await fetchMe())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'লগইন ব্যর্থ হয়েছে')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ maxWidth: 420, margin: '40px auto' }}>
      <h2>লগইন</h2>
      <form onSubmit={submit}>
        <label htmlFor="email">ইমেইল</label>
        <input id="email" type="email" value={email} required onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="password">পাসওয়ার্ড</label>
        <input
          id="password"
          type="password"
          value={password}
          required
          minLength={8}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="error">{error}</p>}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? 'অপেক্ষা করুন…' : 'লগইন'}
        </button>
      </form>
      <p className="muted">
        <a href="/forgot">পাসওয়ার্ড ভুলে গেছেন?</a>
      </p>
      <p className="muted">
        অ্যাকাউন্ট নেই? <a href="/register">নিবন্ধন করুন</a> · <a href="/privacy">গোপনীয়তা</a> ·{' '}
        <a href="/terms">শর্তাবলি</a>
      </p>
    </div>
  )
}
