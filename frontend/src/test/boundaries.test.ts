import { ESLint } from 'eslint';

// The import boundaries of frontend/CLAUDE.md "Architecture", checked through the real ESLint
// config. Each import is linted as if it were written in a file at that path, so relative
// paths resolve the same way they would in the code.

const FEATURE_ROOT = 'src/features/portfolio/PortfolioPage.tsx';
const FEATURE_NESTED = 'src/features/portfolio/components/KpiGrid.tsx';
const SHARED = 'src/shared/ui/ErrorState.tsx';
const API = 'src/api/endpoints.ts';
// Deeper than any folder the features have today: the rule must not depend on depth.
const FEATURE_DEEP = 'src/features/portfolio/a/b/c/d/Deep.tsx';

// A file that does not exist is linted with typescript-eslint's default project.
const eslint = new ESLint({
  overrideConfig: {
    languageOptions: { parserOptions: { projectService: { allowDefaultProject: [FEATURE_DEEP] } } },
  },
});

async function boundaryErrors(filePath: string, source: string): Promise<string[]> {
  const [result] = await eslint.lintText(`${source}\nexport const probe = 1;\n`, { filePath });
  return (result?.messages ?? [])
    .filter((m) => m.fatal === true || m.ruleId === 'local/import-boundaries')
    .map((m) => (m.fatal ? `fatal: ${m.message}` : (m.ruleId ?? '')));
}

describe('import boundaries', { timeout: 30_000 }, () => {
  // The first lint builds typescript-eslint's program (and, for FEATURE_DEEP, its default
  // project), which alone can take most of the 30 s on a loaded machine. Pay that cold start
  // once here, with its own budget, so no case is charged for it.
  beforeAll(async () => {
    await boundaryErrors(FEATURE_ROOT, '');
    await boundaryErrors(FEATURE_DEEP, '');
  }, 120_000);

  it.each([
    [FEATURE_ROOT, "import '@/features/ledger/LedgerPage';"],
    [FEATURE_ROOT, "import '../ledger/LedgerPage';"],
    [FEATURE_NESTED, "import '../../ledger/hooks/useLedger';"],
    [FEATURE_ROOT, "import '@/app/routes';"],
    [FEATURE_ROOT, "import '@/app/theme';"],
    [FEATURE_ROOT, "import '../../app/paths';"],
    [SHARED, "import '@/features/ledger/LedgerPage';"],
    [SHARED, "import '../../features/ledger/LedgerPage';"],
    [SHARED, "import '@/app/paths';"],
    [API, "import '../app/paths';"],
    // Equivalent spellings of a forbidden path are forbidden too.
    [FEATURE_ROOT, "import './../ledger/LedgerPage';"],
    [FEATURE_NESTED, "import './.././../ledger/hooks/useLedger';"],
    [SHARED, "import './../../features/ledger/LedgerPage';"],
    [API, "import './../app/routes';"],
    [FEATURE_ROOT, "export * from '../ledger/LedgerPage';"],
    [FEATURE_ROOT, "export const page = () => import('../ledger/LedgerPage');"],
    // At any depth.
    [FEATURE_DEEP, "import '@/app/theme';"],
    [FEATURE_DEEP, "import '../../../../../ledger/LedgerPage';"],
    // Relative paths stay inside the feature; api and shared are imported with @/.
    [FEATURE_NESTED, "import '../../../shared/format';"],
  ])('plan §1 rejects, in %s: %s', async (filePath, source) => {
    expect(await boundaryErrors(filePath, source)).toEqual(['local/import-boundaries']);
  });

  it.each([
    [FEATURE_ROOT, "import './components/KpiGrid';"],
    [FEATURE_NESTED, "import '../hooks/usePortfolio';"],
    [FEATURE_NESTED, "import './SignedFigure';"],
    [FEATURE_ROOT, "import '@/app/paths';"],
    [FEATURE_ROOT, "import '@/shared/format';"],
    [FEATURE_ROOT, "import '@/api/endpoints';"],
    [SHARED, "import '@/shared/format';"],
    [SHARED, "import '../format';"],
    [FEATURE_DEEP, "import '../../../../hooks/usePortfolio';"],
    [FEATURE_DEEP, "import '@/app/paths';"],
  ])('plan §1 allows, in %s: %s', async (filePath, source) => {
    expect(await boundaryErrors(filePath, source)).toEqual([]);
  });
});
