import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, KeyRound, LogOut, Moon, Sun, Trash2 } from 'lucide-react'
import { apiBase, del, generateInviteCode } from '../../api'
import { useAuth } from '../../AuthContext'
import { Badge, Button, Card } from '../../components/ui'
import { friendlyError } from '../../errors'
import { getLang, setLang, t } from '../../i18n'
import { currentTheme, toggleTheme } from '../../lib/theme'

export default function MePage() {
  const { me, signOut } = useAuth()
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [invite, setInvite] = useState<{ code: string; expires_in_minutes: number } | null>(null)
  const [inviteBusy, setInviteBusy] = useState(false)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const dark = currentTheme() === 'dark'

  const createInvite = async () => {
    setInviteBusy(true)
    setInviteError(null)
    try {
      setInvite(await generateInviteCode())
    } catch (e) {
      setInviteError(friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric'))
    } finally {
      setInviteBusy(false)
    }
  }

  const deleteAccount = async () => {
    setBusy(true)
    setError(null)
    try {
      await del('/users/me')
      signOut()
      navigate('/login')
    } catch (e) {
      setError(friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric'))
      setBusy(false)
    }
  }

  return (
    <main className="shell-main">
      <section className="section-head">
        <h2>{t('me')}</h2>
      </section>

      <Card>
        <div className="row-flex">
          <span className="quick-icon" style={{ width: 60, height: 60, borderRadius: 20 }}>
            {(me?.name ?? '?').slice(0, 1).toUpperCase()}
          </span>
          <div className="row-main">
            <div className="row-title" style={{ fontSize: 'var(--fs-lg)' }}>{me?.name ?? me?.email}</div>
            <div className="row-sub">{me?.email}</div>
            <div style={{ marginTop: '6px' }}>
              <Badge>{me?.role}</Badge>
              {me?.class_level ? (
                <Badge tone="teal" >{t('classLabel')} {me.class_level}</Badge>
              ) : null}
            </div>
          </div>
          <Button variant="danger" size="sm" onClick={signOut}>
            <LogOut size={16} aria-hidden /> {t('logout')}
          </Button>
        </div>
      </Card>

      {me?.role === 'student' && (
        <Card>
          <div className="card-title">{t('parentInviteTitle')}</div>
          <p className="muted" style={{ marginTop: 0, fontSize: 'var(--fs-sm)' }}>
            {t('parentInviteHint')}
          </p>
          {invite ? (
            <div className="stack">
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                <KeyRound size={18} aria-hidden />
                <strong style={{ fontSize: 'var(--fs-lg)', letterSpacing: '1px' }}>{invite.code}</strong>
              </div>
              <p className="muted" style={{ margin: 0, fontSize: 'var(--fs-sm)' }}>
                {t('parentInviteExpires', { minutes: invite.expires_in_minutes })}
              </p>
            </div>
          ) : (
            <Button variant="teal" onClick={createInvite} disabled={inviteBusy}>
              {inviteBusy ? <span className="spinner" aria-hidden /> : <KeyRound size={16} aria-hidden />}
              {t('parentInviteGenerate')}
            </Button>
          )}
          {inviteError && <p className="error" style={{ margin: 0 }}>{inviteError}</p>}
        </Card>
      )}

      <Card>
        <div className="card-title">{t('settings')}</div>
        <div className="field">
          <label htmlFor="lang">{t('language')}</label>
          <select
            id="lang"
            className="select"
            value={getLang()}
            onChange={(e) => {
              const v = e.target.value as 'bn' | 'en'
              setLang(v)
              document.documentElement.setAttribute('lang', v)
              navigate(0)
            }}
          >
            <option value="bn">বাংলা</option>
            <option value="en">English</option>
          </select>
        </div>
        <div className="row-flex" style={{ justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontWeight: 600 }}>{t('appearance')}</div>
            <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{t('darkMode')}</div>
          </div>
          <button className="icon-btn" aria-label={t('darkMode')} onClick={() => { toggleTheme(); navigate(0) }}>
            {dark ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
          </button>
        </div>
      </Card>

      <Card>
        <div className="card-title">{t('account')}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <a className="btn btn-ghost" href={`${apiBase}/users/me/export`} style={{ justifyContent: 'flex-start' }}>
            <Download size={18} aria-hidden /> {t('exportData')}
          </a>
          {!confirming ? (
            <Button variant="danger" onClick={() => setConfirming(true)}>
              <Trash2 size={18} aria-hidden /> {t('deleteAccount')}
            </Button>
          ) : (
            <div className="stack">
              <p className="error" style={{ margin: 0 }}>{t('deleteWarning')}</p>
              <div className="row-flex">
                <Button variant="danger" onClick={deleteAccount} disabled={busy}>
                  {t('confirmDelete')}
                </Button>
                <Button variant="ghost" onClick={() => setConfirming(false)}>
                  {t('cancel')}
                </Button>
              </div>
              {error && <p className="error" style={{ margin: 0 }}>{error}</p>}
            </div>
          )}
        </div>
      </Card>
    </main>
  )
}
