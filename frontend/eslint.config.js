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
  // Dependencies point inward (frontend/CLAUDE.md "Architecture"): a feature never imports
  // another feature (its own files are imported relatively), and shared/api never import
  // features or app.
  {
    files: ['src/features/**/*.{ts,tsx}'],
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
              group: ['@/app/routes', '@/app/providers', '@/app/navigation'],
              message: 'Features do not depend on app composition.',
            },
          ],
        },
      ],
    },
  },
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
