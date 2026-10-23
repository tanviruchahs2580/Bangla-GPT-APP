import { expect, test } from '@playwright/test'
import { axeRoute, describeFindings, signIn, useVariant, VARIANTS, type AxeFinding } from './a11y'

/**
 * AUD-G-10 / G-10: axe on *every* route, light and dark, bn and en.
 *
 * The G-10 bar is zero serious or critical violations. Moderate and minor
 * findings are printed (so they are visible in the run log) but do not fail
 * the sweep; anything serious or critical fails with the rule id, the impact
 * and the offending selectors.
 *
 * Route inventory mirrors `src/main.tsx` one-for-one: public routes plus each
 * role's guarded group. A route added there without being added here is a
 * gap, so the list is deliberately explicit rather than derived.
 */

const PUBLIC_ROUTES = [
  '/welcome',
  '/login',
  '/register',
  '/forgot',
  '/privacy',
  '/terms',
  '/status',
]

interface RoleGroup {
  name: string
  email: string
  routes: string[]
}

const ROLE_GROUPS: RoleGroup[] = [
  {
    name: 'student',
    email: 'student1@e2e.test',
    routes: ['/student', '/student/learn', '/student/tutor', '/student/quiz', '/student/me'],
  },
  {
    name: 'teacher',
    email: 'teacher1@e2e.test',
    routes: [
      '/teacher',
      '/teacher/create',
      '/teacher/classes',
      '/teacher/assessments',
      '/teacher/analytics',
      '/teacher/profile',
    ],
  },
  { name: 'parent', email: 'parent1@e2e.test', routes: ['/parent'] },
  { name: 'admin', email: 'admin1@e2e.test', routes: ['/admin'] },
  { name: 'school_admin', email: 'schooladmin1@e2e.test', routes: ['/school'] },
]

// A group test walks every route of a role in one of the four variants; the
// browser's own desktop viewport keeps the run representative without a
// device-matrix multiplier on top.
test.describe.configure({ timeout: 15 * 60_000 })

for (const variant of VARIANTS) {
  test(`[public] axe serious/critical = 0 (${variant.theme}-${variant.lang})`, async ({ page }) => {
    await useVariant(page, variant)
    const blocking: AxeFinding[] = []
    const advisory: AxeFinding[] = []
    for (const route of PUBLIC_ROUTES) {
      const result = await axeRoute(page, route, variant)
      blocking.push(...result.blocking)
      advisory.push(...result.advisory)
    }
    if (advisory.length)
      console.log(`advisory (moderate/minor) findings:\n${describeFindings(advisory)}`)
    expect(blocking, describeFindings(blocking)).toEqual([])
  })
}

for (const group of ROLE_GROUPS) {
  for (const variant of VARIANTS) {
    test(`[${group.name}] axe serious/critical = 0 (${variant.theme}-${variant.lang})`, async ({
      page,
    }) => {
      await useVariant(page, variant)
      await signIn(page, group.email)
      const blocking: AxeFinding[] = []
      const advisory: AxeFinding[] = []
      for (const route of group.routes) {
        const result = await axeRoute(page, route, variant)
        blocking.push(...result.blocking)
        advisory.push(...result.advisory)
      }
      if (advisory.length)
        console.log(`advisory (moderate/minor) findings:\n${describeFindings(advisory)}`)
      expect(blocking, describeFindings(blocking)).toEqual([])
    })
  }
}
