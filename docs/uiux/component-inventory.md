# UI component inventory and variants (G-02 / AUD-G-09)

Status: written 2026-10-19 for the R3 audit pass. This is the "variants
documented" half of G-02: *one implementation per UI pattern*, with what each
variant means. It is derived from the tree, not from a design file — every
line corresponds to code that exists at this commit, and the numbers were
produced by counting call sites.

## The primitives (`apps/web/src/components/ui.tsx`)

| Primitive | Variants / props | Call sites (2026-10-19) |
|---|---|---|
| `Button` | `variant`: `primary`, `teal`, `ghost`, `soft`, `danger`, `default`; `size`: `sm`, `md`, `lg`; `block`, `loading` | 20 JSX uses |
| `Card` | optional `title` + `action` header row | 66 |
| `Badge` | `tone`: `default`, `ok`, `warn`, `teal`, `ai` | 27 |
| `Field` | `label`, `htmlFor`, `error`, `hint`; wires `id`, `aria-invalid`, `aria-describedby` onto the single control it wraps | 10 |
| `NumberInput` | `min`/`max`/`fallback`; accepts Bengali digits (`lib/digits.ts`) | 12 |
| `Segmented` | generic over the option keys; `role="group"` + `aria-pressed` | 2 |
| `Modal` | `open`, `onClose`, `title`, `footer`, `wide`; portal, focus trap, scroll lock, Escape, focus restore, backdrop presentation-role | 2 |
| `EmptyState` | `title`, `sub`, `action` | 1 |
| `LoadError` | `message`, `onRetry`; `role="alert"` + a retry control | 3 |
| `Skeleton` | `variant`: `text`, `card`, `row`, `avatar`; `w`/`h` | 7 |
| `ProgressRing` | `value`, `size`, `label` | 5 |
| `Stat` | `value`, `label` | 7 |
| `Avatar` | size variants | 2 |
| `Row` | `title`, `sub`, `trailing`, `onClick` | 0 — exported, no page uses it |
| `Spinner` | `label` (defaults to `t("loading")`) | 0 — exported, no page uses it |

`Row` and `Spinner` are kept deliberately (they are the shared
implementations the next page should reach for instead of hand-rolling one)
but they are currently **unused by any page**: recorded here rather than
deleted silently, so the next inventory pass can decide — if neither is used
by the next release, delete both and their tests.

## Other shared components (`apps/web/src/components/`)

| Component | What it owns |
|---|---|
| `AppShell.tsx` (`OfflineBanner`, nav, topbar, sign-out) | the one navigation landmark + the one offline banner per page |
| `SkipLink` | the bypass link, first in the tab order, targets `#main-content` |
| `BrandMark`, `AiSparkle` | the one logo/icon mark (inline SVG, `aria-hidden` unless titled) |
| `NotificationBell` | bell + panel, one implementation for all roles |
| `SearchBox` | the debounced search field used by admin/teacher lists |
| `ConversationChip` | the tutor's conversation switcher |
| `VoiceButton` | speech input, renders nothing when the browser has no recognition API |
| `ClassLevelSelect` | the class-level picker (1–12, Bengali digits accepted) |
| `PublicLanguageToggle` | the bn/en switch on public pages |
| `RouteErrorBoundary` | the one route-level error surface (`role="alert"`, retry) |

## One implementation per pattern — what that means here

| Pattern | Single implementation | Evidence |
|---|---|---|
| Dialog | `Modal` (portal, trap, Escape, restore) | `EvidenceModal` in `AITutorPage.tsx` and the thumbs-down reason dialog both render `Modal`; `rg "modal-backdrop"` finds it only in `ui.tsx` and its test |
| Empty state | `EmptyState` | the tutor's empty chat now renders it (this pass); `rg "empty-state"` outside `ui.tsx` finds no page markup |
| Error state | `LoadError` (+ `RouteErrorBoundary` for route-level) | every `isLoading` branch in a data view pairs with `LoadError` on failure rather than falling through to "no data" |
| Loading | `Skeleton` (and `Spinner` for short waits) | the resilience e2e asserts a skeleton is visible on a delayed API, and that no unlabelled spinner is ever left on screen |
| Form field | `Field` / `NumberInput` | `aria-invalid` + `aria-describedby` are wired by the primitive, not per page |
| Toast | `lib/toast.ts` (`role="status"`, polite live region, max 3) | single region created on demand |
| Table | `.table` CSS + `Row` | list rows are `Row` or `.row` markup; no second table component exists |

## Known residuals (honest, not fixed here)

1. **Raw class usage instead of the primitive.** 29 `btn btn-*` and 42
   `className="card"` occurrences live directly in page markup (mostly
   `LearnPage.tsx`, `HomePage.tsx`, `MePage.tsx`). They use the *same* CSS
   classes the primitives emit, so the design is not duplicated — the
   component boundary is. Each is a mechanical migration with a screenshot
   question attached, which is why it is not part of this pass.
2. **Icons.** One icon set (`lucide-react`) is used everywhere; decorative
   icons carry `aria-hidden`. The logo is inline SVG (`BrandMark`), not from
   the set, because it is a brand mark.
3. **No Storybook or visual component catalogue.** The variants table above
   and the screenshot matrix (`e2e/visual.spec.ts`, `e2e/reflow.spec.ts`) are
   the catalogue; introducing a component workbench is out of scope for an
   audit pass and would add a build dependency.
