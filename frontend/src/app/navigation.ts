import { IconBriefcase, IconListDetails, IconShieldCheck, IconStack2 } from '@tabler/icons-react';

import type { NavItem } from '@/shared/layout/Sidebar';

import { paths } from './paths';

// Order and labels follow the design's "Navegação principal".
export const navItems: NavItem[] = [
  { label: 'Central de Controle', to: paths.controlCenter, icon: IconShieldCheck },
  { label: 'Ativos', to: paths.assets, icon: IconStack2 },
  { label: 'Carteira', to: paths.portfolio, icon: IconBriefcase },
  { label: 'Lançamentos', to: paths.ledger, icon: IconListDetails },
];
