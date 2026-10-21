// ESLint flat config for the web app (FEQ-02 / AUD-0009).
//
// Prettier already owns formatting; ESLint owns correctness. The two are kept
// apart deliberately - running a formatter and a linter that both rewrite
// whitespace produces conflicts and review noise.
//
// Rule selection is deliberate rather than "everything on":
//   typescript-eslint  type-aware linting; `no-floating-promises` and
//                      `no-misused-promises` catch the bugs that actually
//                      happen in an async React app.
//   react-hooks        the rules of hooks, plus the compiler-driven extras.
//   jsx-a11y           accessibility defects that ship silently otherwise.
//   react-refresh      HMR-only export rules from the Vite template.
//
// `--max-warnings 0` is enforced in CI, so a warning is a failure.

import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['dist', 'coverage', 'node_modules', 'android', 'ios'],
  },

  // ---- source: full rules -------------------------------------------------
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      // Registered once here because react-hooks' `recommended` config is
      // still eslintrc-shaped (plugins as an array), which flat config rejects.
      // Its rules are spread in `rules` below.
      'react-hooks': reactHooks,
      'jsx-a11y': jsxA11y,
    },
    settings: {
      react: { version: 'detect' },
    },
    rules: {
      // `recommended` carries rules-of-hooks and exhaustive-deps;
      // `recommended-latest` adds the compiler-driven extras.
      ...reactHooks.configs.recommended.rules,
      ...reactHooks.configs['recommended-latest'].rules,
      ...jsxA11y.flatConfigs.recommended.rules,

      // Unused arguments prefixed with `_` are deliberate (callbacks,
      // interface conformance); anything else unused is a mistake.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
          destructuredArrayIgnorePattern: '^_',
        },
      ],

      // `any` defeats the type system; the codebase is fully typed, so this
      // should be rare and each occurrence needs a real reason.
      '@typescript-eslint/no-explicit-any': 'error',

      // Floating promises are the classic unhandled-rejection bug in React.
      '@typescript-eslint/no-floating-promises': 'error',
      // Void-returning positions are checked (so an async callback passed to
      // forEach still gets caught), but attribute handlers are exempt: JSX
      // event handlers are void by definition and `onClick={async () => ...}`
      // is the idiomatic form. Without this exemption the rule fires 57 times
      // on correct code.
      '@typescript-eslint/no-misused-promises': [
        'error',
        { checksVoidReturn: { attributes: false } },
      ],

      // Non-null assertions. Left OFF, with the reason recorded rather than
      // suppressed line by line: all 14 remaining sites are the query
      // enable-guard idiom -
      //     useQuery({ queryFn: () => f(active!, id), enabled: !!active })
      // where TypeScript cannot see that `enabled` gates the call. Rewriting
      // each one into a redundant `if (!active) return` would add noise
      // without removing a real possibility of a null crash.
      // Re-enable this if the codebase stops using react-query guards.
      '@typescript-eslint/no-non-null-assertion': 'off',

      // Fast-refresh granularity only: it complains when a module exports a
      // component alongside a hook or constant, which costs a full reload in
      // dev but is not a defect in the shipped code. Colocating a page with
      // its helpers is the more common, more readable layout.
      'react-refresh/only-export-components': 'off',

      // Console noise in shipped UI code is usually debugging left behind.
      'no-console': ['warn', { allow: ['warn', 'error'] }],

      // `role="student"` on <RequireAuth> is a prop of our own component, not
      // a DOM aria role; ignoreNonDOM stops jsx-a11y from reading it as one.
      'jsx-a11y/aria-role': ['error', { ignoreNonDOM: true }],

      eqeqeq: ['error', 'smart'],
      'prefer-const': 'error',
      'no-var': 'error',
    },
  },

  // ---- tests: the few rules a test double legitimately breaks -------------
  // Each remaining exemption was measured: with the whole block removed these
  // are the only rules the current test sources violate (require-await 17,
  // unbound-method 5, no-floating-promises 2, no-unsafe-assignment 2, on
  // 2026-10-19). Anything else applies to tests exactly as it does to app
  // code, `no-explicit-any` included.
  {
    files: ['src/**/*.{test,spec}.{ts,tsx}', 'src/test/**/*.{ts,tsx}'],
    rules: {
      // `expect(spy.method).toHaveBeenCalledWith(...)` asserts through an
      // unbound method reference; that is the Vitest idiom.
      '@typescript-eslint/unbound-method': 'off',
      // `logout()` and friends are fire-and-forget in these tests by design.
      '@typescript-eslint/no-floating-promises': 'off',
      // `vi.fn(async () => ...)` doubles a Promise-returning function; the
      // body itself has nothing to await.
      '@typescript-eslint/require-await': 'off',
      // Vitest asymmetric matchers (`expect.stringContaining`) are typed
      // `any`; assigning one into an expected payload is their shape.
      '@typescript-eslint/no-unsafe-assignment': 'off',
    },
  },

  // ---- config files: node, not browser ------------------------------------
  {
    files: ['*.config.{ts,js,mts}', 'eslint.config.js'],
    languageOptions: {
      globals: globals.node,
    },
  },
);
