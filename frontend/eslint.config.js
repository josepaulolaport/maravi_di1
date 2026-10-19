import path from 'node:path';

import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const SRC = path.join(import.meta.dirname, 'src');

/** `features/ledger/x.ts` → { top: 'features', feature: 'ledger' } (paths relative to src). */
function areaOf(file) {
  const [top, feature] = file.split('/');
  return { top, feature: top === 'features' ? feature : undefined };
}

// The import boundaries, checked on where an import resolves (so "./../x", "../x" and any
// folder depth are the same), not on how it is spelled:
// - a feature imports @/api, @/shared, @/app/paths and its own files (relatively, and only
//   those relatively), never another feature or the rest of app;
// - shared and api (tests aside) never import features or app.
const importBoundaries = {
  meta: {
    type: 'problem',
    schema: [],
    messages: {
      otherFeature: 'Features are independent; move shared code to @/shared.',
      ownFeatureAlias: "Import your own feature's files with a relative path.",
      relativeOutside: 'A relative import stays inside its feature; use @/ for api and shared.',
      app: 'From app, a feature imports only @/app/paths.',
      inward: 'shared and api must not depend on features or app.',
    },
  },
  create(context) {
    const from = path.relative(SRC, context.filename).split(path.sep).join('/');
    if (from.startsWith('..')) return {};
    const source = areaOf(from);
    const isTest = /\.test\.tsx?$/.test(from);
    const check = (node) => {
      const specifier = node.source?.value;
      if (typeof specifier !== 'string') return;
      let target;
      if (specifier.startsWith('@/')) target = path.posix.normalize(specifier.slice(2));
      else if (specifier.startsWith('.'))
        target = path.posix.normalize(path.posix.join(path.posix.dirname(from), specifier));
      else return; // a package
      const dest = areaOf(target);
      const report = (messageId) => {
        context.report({ node: node.source, messageId });
      };
      if (source.top === 'features') {
        if (dest.top === 'features' && dest.feature !== source.feature) report('otherFeature');
        else if (dest.top === 'features' && specifier.startsWith('@/')) report('ownFeatureAlias');
        else if (specifier.startsWith('.') && dest.top !== 'features') report('relativeOutside');
        else if (dest.top === 'app' && !/^app\/paths(\.tsx?)?$/.test(target)) report('app');
      } else if ((source.top === 'shared' || source.top === 'api') && !isTest) {
        if (dest.top === 'features' || dest.top === 'app') report('inward');
      }
    };
    return {
      ImportDeclaration: check,
      ExportNamedDeclaration: check,
      ExportAllDeclaration: check,
      ImportExpression: check,
    };
  },
};

export default tseslint.config(
  { ignores: ['dist'] },
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
  // Dependencies point inward (frontend/CLAUDE.md "Architecture").
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { local: { rules: { 'import-boundaries': importBoundaries } } },
    rules: { 'local/import-boundaries': 'error' },
  },
  {
    files: ['eslint.config.js'],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  prettier,
);
