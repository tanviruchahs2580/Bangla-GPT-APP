import { useState } from 'react'
import type { MeResponse } from '../api'
import { fetchMe, login, register } from '../api'

export default function RegisterPage({ onRegister }: { onRegister: (me: MeResponse | null) => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<'student' | 'teacher' | 'parent'>('student')
  const [classLevel, setClassLevel] = useState(6)
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (role === 'student' && !consent) {
      setError('শিক্ষার্থী নিবন্ধনের জন্য অভিভাবকের সম্মতি আবশ্যক')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await register({
        email,
        password,
        name,
        role,
        class_level: role === 'student' ? classLevel : undefined,
        guardian_consent: role === 'student',
      })
      await login(email, password)
      onRegister(await fetchMe())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'নিবন্ধন ব্যর্থ হয়েছে')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ maxWidth: 460, margin: '40px auto' }}>
      <h2>নিবন্ধন</h2>
      <form onSubmit={submit}>
        <label htmlFor="role">ভূমিকা</label>
        <select id="role" value={role} onChange={(e) => setRole(e.target.value as typeof role)}>
          <option value="student">শিক্ষার্থী</option>
          <option value="teacher">শিক্ষক</option>
          <option value="parent">অভিভাবক</option>
        </select>
        <label htmlFor="name">নাম</label>
        <input id="name" value={name} required minLength={2} onChange={(e) => setName(e.target.value)} />
        <label htmlFor="remail">ইমেইল</label>
        <input id="remail" type="email" value={email} required onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="rpassword">পাসওয়ার্ড (কমপক্ষে ৮ অক্ষর)</label>
        <input
          id="rpassword"
          type="password"
          value={password}
          required
          minLength={8}
          onChange={(e) => setPassword(e.target.value)}
        />
        {role === 'student' && (
          <>
            <label htmlFor="class">শ্রেণি (১-১২)</label>
            <input
              id="class"
              type="number"
              min={1}
              max={12}
              value={classLevel}
              onChange={(e) => setClassLevel(Number(e.target.value))}
            />
            <label htmlFor="consent" className="muted" style={{ display: 'flex', gap: 8 }}>
              <input
                id="consent"
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                required
              />
              <span>
                আমি অভিভাবক হিসেবে বা অভিভাবকের সম্মতিক্রমে নিবন্ধন করছি এবং{' '}
                <a href="/privacy" target="_blank" rel="noreferrer">
                  গোপনীয়তা নীতি
                </a>{' '}
                ও{' '}
                <a href="/terms" target="_blank" rel="noreferrer">
                  শর্তাবলি
                </a>{' '}
                পড়ে সম্মত হচ্ছি।
              </span>
            </label>
          </>
        )}
        {error && <p className="error">{error}</p>}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? 'অপেক্ষা করুন…' : 'নিবন্ধন'}
        </button>
      </form>
      <p className="muted">
        অ্যাকাউন্ট আছে? <a href="/login">লগইন করুন</a> · <a href="/privacy">গোপনীয়তা</a> ·{' '}
        <a href="/terms">শর্তাবলি</a>
      </p>
    </div>
  )
}
