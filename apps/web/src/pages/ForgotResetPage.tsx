import { useState } from 'react'
import { forgotPassword, resetPassword } from '../api'

export default function ForgotResetPage() {
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [requested, setRequested] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function requestToken(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await forgotPassword(email)
      setRequested(true)
      setMessage(
        'ইমেইল পাঠানো হয়েছে (যদি অ্যাকাউন্ট থাকে)। ৩০ মিনিটের মধ্যে টোকেনটি ব্যবহার করুন।',
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ব্যর্থ হয়েছে')
    } finally {
      setBusy(false)
    }
  }

  async function doReset(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await resetPassword(token, newPassword)
      window.location.href = '/student'
    } catch (err) {
      setError(err instanceof Error ? err.message : 'রিসেট ব্যর্থ হয়েছে')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ maxWidth: 460, margin: '40px auto' }}>
      <h2>পাসওয়ার্ড রিসেট</h2>
      {!requested ? (
        <form onSubmit={requestToken}>
          <label htmlFor="femail">ইমেইল</label>
          <input
            id="femail"
            type="email"
            value={email}
            required
            onChange={(e) => setEmail(e.target.value)}
          />
          {error && <p className="error">{error}</p>}
          <button className="primary" type="submit" disabled={busy}>
            {busy ? 'অপেক্ষা করুন…' : 'রিসেট টোকেন চান'}
          </button>
        </form>
      ) : (
        <>
          {message && <p className="muted">{message}</p>}
          <form onSubmit={doReset}>
            <label htmlFor="rtoken">রিসেট টোকেন</label>
            <input
              id="rtoken"
              value={token}
              required
              minLength={16}
              onChange={(e) => setToken(e.target.value)}
            />
            <label htmlFor="rnewpass">নতুন পাসওয়ার্ড (কমপক্ষে ৮ অক্ষর)</label>
            <input
              id="rnewpass"
              type="password"
              value={newPassword}
              required
              minLength={8}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            {error && <p className="error">{error}</p>}
            <button className="primary" type="submit" disabled={busy}>
              {busy ? 'অপেক্ষা করুন…' : 'পাসওয়ার্ড রিসেট করুন'}
            </button>
          </form>
        </>
      )}
      <p className="muted">
        অ্যাকাউন্ট আছে? <a href="/login">লগইন করুন</a>
      </p>
    </div>
  )
}
