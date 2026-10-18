import { ESLint } from 'eslint';

// The import boundaries of frontend/CLAUDE.md "Architecture", checked through the real ESLint
// config. Each import is linted as if it were written in an existing file at that depth, so
// relative paths resolve the same way they would in the code.

const FEATURE_ROOT = 'src/features/portfolio/PortfolioPage.tsx';
const FEATURE_NESTED = 'src/features/portfolio/components/KpiGrid.tsx';
const SHARED = 'src/shared/ui/ErrorState.tsx';
const API = 'src/api/endpoints.ts';

const eslint = new ESLint();

async function boundaryErrors(filePath: string, source: string): Promise<string[]> {
  const [result] = await eslint.lintText(`${source}\nexport const probe = 1;\n`, { filePath });
  return (result?.messages ?? [])
    .filter((m) => m.ruleId === 'no-restricted-imports')
    .map((m) => m.message);
}

describe('import boundaries', { timeout: 30_000 }, () => {
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
  ])('plan §1 rejects, in %s: %s', async (filePath, source) => {
    expect(await boundaryErrors(filePath, source)).not.toEqual([]);
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
  ])('plan §1 allows, in %s: %s', async (filePath, source) => {
    expect(await boundaryErrors(filePath, source)).toEqual([]);
  });
});
