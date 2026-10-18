import { ActionIcon, AppShell, Box, Group, Stack, Tooltip } from '@mantine/core';
import { IconLayoutSidebarLeftCollapse, type Icon } from '@tabler/icons-react';
import { NavLink } from 'react-router';

import classes from './Sidebar.module.css';

export interface NavItem {
  label: string;
  to: string;
  icon: Icon;
}

interface SidebarProps {
  navItems: NavItem[];
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ navItems, collapsed, onToggle }: SidebarProps) {
  const toggleLabel = collapsed ? 'Expandir navegação' : 'Recolher navegação';

  return (
    <AppShell.Navbar className={classes.navbar} aria-label="Navegação principal">
      <Group
        className={`${classes.header} ${collapsed ? classes.headerCollapsed : ''}`}
        justify={collapsed ? 'center' : 'space-between'}
        wrap="nowrap"
      >
        {collapsed ? (
          <Box className={classes.brand} role="img" aria-label="Maravi Backoffice">
            M
          </Box>
        ) : (
          <Box>
            <div className={classes.brand}>MARAVI</div>
            <div className={classes.brandSub}>BACKOFFICE</div>
          </Box>
        )}
        <ActionIcon
          variant="subtle"
          className={classes.toggle}
          onClick={onToggle}
          aria-label={toggleLabel}
          title={toggleLabel}
          aria-expanded={!collapsed}
          aria-controls="primary-navigation"
        >
          <IconLayoutSidebarLeftCollapse
            size={18}
            stroke={1.5}
            className={collapsed ? classes.toggleIconCollapsed : undefined}
          />
        </ActionIcon>
      </Group>

      <nav id="primary-navigation" aria-label="Módulos">
        <Stack gap={4} px={12} py={16}>
          {navItems.map(({ label, to, icon: ItemIcon }) => (
            <Tooltip key={to} label={label} position="right" disabled={!collapsed} withArrow>
              <NavLink
                to={to}
                aria-label={label}
                className={`${classes.link} ${collapsed ? classes.linkCollapsed : ''}`}
              >
                <ItemIcon size={20} stroke={1.5} className={classes.icon} aria-hidden />
                {!collapsed && <span>{label}</span>}
              </NavLink>
            </Tooltip>
          ))}
        </Stack>
      </nav>
    </AppShell.Navbar>
  );
}
