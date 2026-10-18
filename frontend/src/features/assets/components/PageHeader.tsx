import { Anchor, Breadcrumbs, Group, Stack, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';
import { Link } from 'react-router';

export interface Crumb {
  label: string;
  /** Omitted for the current page, the last crumb. */
  to?: string;
}

interface PageHeaderProps {
  crumbs: Crumb[];
  title: string;
  /** Next to the title (class badge, maturity badge). */
  badge?: ReactNode;
  subtitle?: ReactNode;
  /** Right-aligned actions ("Novo contrato", "Registrar preço"). */
  actions?: ReactNode;
}

/** Ativos page header: breadcrumb `Ativos / DI1 / DI1F28`, title and actions (design 2:165, 2:340). */
export function PageHeader({ crumbs, title, badge, subtitle, actions }: PageHeaderProps) {
  return (
    <Stack gap="xs">
      <nav aria-label="Trilha">
        <Breadcrumbs separator="/" fz="xs">
          {crumbs.map((crumb) =>
            crumb.to ? (
              <Anchor key={crumb.label} component={Link} to={crumb.to} size="xs" c="dimmed">
                {crumb.label}
              </Anchor>
            ) : (
              <Text key={crumb.label} size="xs" fw={500} aria-current="page">
                {crumb.label}
              </Text>
            ),
          )}
        </Breadcrumbs>
      </nav>
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Group gap="sm">
            <Title order={1} size="h2" fw={500}>
              {title}
            </Title>
            {badge}
          </Group>
          {subtitle && (
            <Text size="sm" c="dimmed">
              {subtitle}
            </Text>
          )}
        </Stack>
        {actions}
      </Group>
    </Stack>
  );
}
