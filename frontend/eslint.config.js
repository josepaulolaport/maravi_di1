import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'public/mockServiceWorker.js'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Money and rates are decimal strings; parsing them into floats is forbidden (CLAUDE.md).
      'no-restricted-globals': ['error', { name: 'parseFloat', message: 'Decimals stay strings.' }],
      'no-restricted-properties': [
        'error',
        { object: 'Number', property: 'parseFloat', message: 'Decimals stay strings.' },
        { object: 'Math', property: 'round', message: 'The backend rounds; the UI only formats.' },
      ],
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
    },
  },
  // Dependencies point inward (frontend/CLAUDE.md "Architecture"): a feature imports only
  // @/api, @/shared, @/app/paths and its own files; shared and api never import features or
  // app. Relative paths are checked too: a relative import may not climb out of its feature
  // (one rule block per folder depth, since flat config replaces a rule's options per block).
  ...[0, 1, 2, 3].map((depth) => ({
    files: [`src/features/*/${'*/'.repeat(depth)}*.{ts,tsx}`],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/features/*'],
              message: 'Features are independent; move shared code to @/shared.',
            },
            {
              regex: '^@/app/(?!paths$)',
              message: 'From app, a feature imports only @/app/paths.',
            },
            {
              regex: `^(\\.\\./){${depth + 1},}`,
              message: 'A relative import stays inside its feature; use @/ for api and shared.',
            },
          ],
        },
      ],
    },
  })),
  {
    files: ['src/shared/**/*.{ts,tsx}', 'src/api/**/*.{ts,tsx}'],
    ignores: ['src/**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['@/features/*'], message: 'shared and api must not depend on features.' },
            { group: ['@/app/*'], message: 'shared and api must not depend on app composition.' },
            {
              regex: '^(\\.\\./)+(features|app)(/|$)',
              message: 'shared and api must not depend on features or app.',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['eslint.config.js'],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  prettier,
);
