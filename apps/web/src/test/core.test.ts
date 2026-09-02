import { describe, expect, it } from 'vitest'
import { friendlyError } from '../errors'
import { t } from '../i18n'

describe('friendlyError (B8)', () => {
  it('maps machine codes to localized copy', () => {
    expect(friendlyError({ code: 'email_unverified', message: 'x' }).action).toBe('resend-verification')
    expect(friendlyError({ code: 'rate_limited', message: 'x' }).text).toContain('মিনিট')
  })

  it('falls back to generic copy for unknown codes', () => {
    const out = friendlyError({ code: 'zzz_unknown', message: 'weird' })
    expect(out.text.length).toBeGreaterThan(5)
  })

  it('handles legacy string details and nulls', () => {
    expect(friendlyError(null).text).toBeTruthy()
    expect(friendlyError('Email already registered').text).toBeTruthy()
  })
})

describe('i18n (B9)', () => {
  it('defaults to Bengali with interpolation support', () => {
    const out = t('partialQuizNote', { got: 4, want: 5 })
    expect(out).toContain('4')
    expect(out).toContain('5')
  })
})
