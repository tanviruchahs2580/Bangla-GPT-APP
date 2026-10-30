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
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

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

      // Non-null assertions (`x!`) hide a real null from the type checker.
      // FE-02: this rule was off with a rationale that the 14 sites were all
      // react-query enable-guard idioms; every production site is now written
      // with an explicit guard instead, so the rule is on. (Tests keep their
      // own override below: asserting a query result is how a test asserts.)
      '@typescript-eslint/no-non-null-assertion': 'error',

      // Fast-refresh granularity only: it complains when a module exports a
      // component alongside a hook or constant, which costs a full reload in
      // dev but is not a defect in the shipped code. Colocating a page with
      // its helpers is the more common, more readable layout.
      'react-refresh/only-export-components': 'off',

      // Console noise in shipped UI code is usually debugging left behind.
      'no-console': ['warn', { allow: ['warn', 'error'] }],

      // FE-03: the >500-line pages are being split (AITutorPage first, its
      // sections now live under src/pages/student/tutor/). The extracted
      // modules are capped immediately so the split cannot regress while the
      // remaining pages land; the rule extends to src/pages as each page is
      // split, and the register's F-094 tracks the remainder.
      'max-lines': 'off',

      // `role="student"` on <RequireAuth> is a prop of our own component, not
      // a DOM aria role; ignoreNonDOM stops jsx-a11y from reading it as one.
      'jsx-a11y/aria-role': ['error', { ignoreNonDOM: true }],

      eqeqeq: ['error', 'smart'],
      'prefer-const': 'error',
      'no-var': 'error',
    },
  },

  // ---- extracted page sections: line budget (FE-03) -----------------------
  {
    files: ['src/pages/student/tutor/**/*.tsx'],
    rules: {
      'max-lines': [
        'error',
        { max: 300, skipBlankLines: true, skipComments: true },
      ],
    },
  },

  // ---- tests: same linter, fewer stylistic rules --------------------------
  {
    files: ['src/**/*.{test,spec}.{ts,tsx}', 'src/test/**/*.{ts,tsx}'],
    rules: {
      // Test doubles legitimately cast and stub.
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unsafe-function-type': 'off',
      // Asserting on a query result in a test is how you assert it was found.
      '@typescript-eslint/no-non-null-assertion': 'off',
      '@typescript-eslint/unbound-method': 'off',
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      // Fixture promises are created and immediately ignored on purpose.
      '@typescript-eslint/no-floating-promises': 'off',
      '@typescript-eslint/require-await': 'off',
      'no-console': 'off',
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
