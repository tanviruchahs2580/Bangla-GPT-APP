import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VoiceButton } from '../components/VoiceButton'
import { t } from '../i18n'
import type { SpeechRecognitionLike } from '../lib/voice'

type Ctor = new () => SpeechRecognitionLike

class FakeRecognition implements SpeechRecognitionLike {
  static instance: FakeRecognition | null = null
  lang = ''
  continuous = false
  interimResults = false
  maxAlternatives = 0
  started = false
  stopped = false
  onresult: SpeechRecognitionLike['onresult'] = null
  onerror: SpeechRecognitionLike['onerror'] = null
  onend: SpeechRecognitionLike['onend'] = null
  constructor() {
    FakeRecognition.instance = this
  }
  start() {
    this.started = true
  }
  stop() {
    this.stopped = true
    this.onend?.()
  }
  abort() {}
}

afterEach(() => {
  const w = window as unknown as Record<string, unknown>
  delete w.SpeechRecognition
  delete w.webkitSpeechRecognition
  FakeRecognition.instance = null
})

describe('S1.12 voice input', () => {
  it('renders nothing when the browser lacks Speech Recognition (no crash)', () => {
    const { container } = render(<VoiceButton onTranscript={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByLabelText(t('voiceMic'))).not.toBeInTheDocument()
  })

  it('records bn-BD speech and hands the transcript to the composer', async () => {
    const w = window as unknown as { SpeechRecognition?: Ctor }
    w.SpeechRecognition = FakeRecognition
    const onTranscript = vi.fn()
    const user = userEvent.setup()
    render(<VoiceButton onTranscript={onTranscript} />)

    const btn = screen.getByLabelText(t('voiceMic'))
    await user.click(btn)

    const rec = FakeRecognition.instance
    expect(rec).not.toBeNull()
    expect(rec!.started).toBe(true)
    expect(rec!.lang).toBe('bn-BD')
    expect(btn).toHaveAttribute('aria-pressed', 'true')

    rec!.onresult?.({ results: [[{ transcript: '  koshe ki  ' }]] })
    expect(onTranscript).toHaveBeenCalledWith('koshe ki')

    await user.click(btn)
    expect(rec!.stopped).toBe(true)
    await waitFor(() => expect(btn).toHaveAttribute('aria-pressed', 'false'))
  })

  it('a mic error just ends listening without throwing', async () => {
    const w = window as unknown as { SpeechRecognition?: Ctor }
    w.SpeechRecognition = FakeRecognition
    const user = userEvent.setup()
    render(<VoiceButton onTranscript={vi.fn()} />)

    const btn = screen.getByLabelText(t('voiceMic'))
    await user.click(btn)
    const rec = FakeRecognition.instance!
    expect(() => rec.onerror?.({ error: 'not-allowed' })).not.toThrow()
    await waitFor(() => expect(btn).toHaveAttribute('aria-pressed', 'false'))
  })
})
