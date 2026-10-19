import { lazy } from 'react';
import { Navigate, type RouteObject } from 'react-router';

import { AppLayout } from '@/shared/layout/AppLayout';
import { NotFoundPage } from '@/shared/layout/NotFoundPage';
import { RouteErrorPage } from '@/shared/layout/RouteErrorPage';

import { navItems } from './navigation';
import { paths } from './paths';

// One bundle per screen: a screen's code loads when it is first opened.
const ControlCenterPage = lazy(() =>
  import('@/features/processing/ControlCenterPage').then((m) => ({ default: m.ControlCenterPage })),
);
const AssetsPage = lazy(() =>
  import('@/features/assets/AssetsPage').then((m) => ({ default: m.AssetsPage })),
);
const ProductPage = lazy(() =>
  import('@/features/assets/ProductPage').then((m) => ({ default: m.ProductPage })),
);
const ContractPage = lazy(() =>
  import('@/features/assets/ContractPage').then((m) => ({ default: m.ContractPage })),
);
const PortfolioPage = lazy(() =>
  import('@/features/portfolio/PortfolioPage').then((m) => ({ default: m.PortfolioPage })),
);
const LedgerPage = lazy(() =>
  import('@/features/ledger/LedgerPage').then((m) => ({ default: m.LedgerPage })),
);

export const routes: RouteObject[] = [
  {
    element: <AppLayout navItems={navItems} />,
    // Last resort, if the shell itself fails.
    errorElement: <RouteErrorPage />,
    children: [
      {
        // A screen that throws is replaced inside the shell; the navigation stays usable.
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, element: <Navigate to={paths.controlCenter} replace /> },
          { path: paths.controlCenter, element: <ControlCenterPage /> },
          { path: paths.assets, element: <AssetsPage /> },
          { path: paths.assetProduct, element: <ProductPage /> },
          { path: paths.assetContract, element: <ContractPage /> },
          { path: paths.portfolio, element: <PortfolioPage /> },
          { path: paths.ledger, element: <LedgerPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
