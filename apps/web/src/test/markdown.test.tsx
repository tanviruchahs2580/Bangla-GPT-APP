import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { SafeMarkdown } from '../lib/safeMarkdown'

describe('SafeMarkdown (S0.3)', () => {
  it('renders inline math as KaTeX', () => {
    const { container } = render(<SafeMarkdown content="Formula $E=mc^2$ test" />)
    // KaTeX renders with class 'katex'
    expect(container.innerHTML).toContain('katex')
    expect(container.textContent).toContain('E=mc')
  })

  it('sanitizes XSS payload — script tag stripped', () => {
    const xss = 'Hello <script>alert(1)</script> world'
    const { container } = render(<SafeMarkdown content={xss} />)
    expect(container.innerHTML).not.toContain('<script>')
    expect(container.textContent).toContain('Hello')
    expect(container.textContent).toContain('world')
  })

  it('renders markdown headings and lists', () => {
    const md = '## Title\n- item 1\n- item 2'
    const { container } = render(<SafeMarkdown content={md} />)
    expect(container.innerHTML).toContain('<h2')
    expect(container.innerHTML).toContain('<li')
  })
})
