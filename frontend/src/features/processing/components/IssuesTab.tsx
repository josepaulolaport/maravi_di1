import { Button, Group, Paper, Stack, Table, Text, VisuallyHidden } from '@mantine/core';
import { IconAlertTriangle, IconCalendarX } from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router';

import { SearchInput } from '@/shared/ui/SearchInput';
import { Loading } from '@/shared/ui/Loading';
import type { Issue, IssueType } from '@/api/contract';
import { assetLinks, ledgerLinks } from '@/app/paths';
import { UNAVAILABLE, countLabel, formatDate } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';
import { Figure } from '@/shared/ui/Figure';

import type { useIssues } from '../hooks/useProcessing';

const ISSUE_TEXT: Record<IssueType, { text: string; icon: ReactNode }> = {
  MISSING_REFERENCE_PRICE: {
    text: 'Preço de referência ausente',
    icon: <IconAlertTriangle size={16} stroke={1.5} />,
  },
  EXPIRED_OPEN_POSITION: {
    text: 'Contrato vencido com posição aberta',
    icon: <IconCalendarX size={16} stroke={1.5} />,
  },
};

/** The action that resolves each issue (§10.3), as a link to where it is done. */
function issueAction(issue: Issue): { label: string; to: string } | null {
  switch (issue.issue_type) {
    case 'MISSING_REFERENCE_PRICE':
      return issue.asset_id && issue.required_price_date
        ? {
            label: 'Definir preço',
            to: assetLinks.contract(issue.asset_id, { register: issue.required_price_date }),
          }
        : null;
    case 'EXPIRED_OPEN_POSITION':
      return issue.asset_code
        ? { label: 'Ver lançamentos', to: ledgerLinks.list({ search: issue.asset_code }) }
        : null;
  }
}

function matchesSearch(issue: Issue, search: string): boolean {
  const needle = search.trim().toLocaleLowerCase('pt-BR');
  if (!needle) return true;
  return [
    issue.asset_code ?? '',
    formatDate(issue.required_price_date),
    formatDate(issue.affected_date),
  ].some((value) => value.toLocaleLowerCase('pt-BR').includes(needle));
}

interface IssuesTabProps {
  issues: ReturnType<typeof useIssues>;
  search: string;
  onSearchChange: (text: string) => void;
}

/** Pendências (§11.1, §10.3): the current actionable issues, two types only (OQ-31). */
export function IssuesTab({ issues, search, onSearchChange }: IssuesTabProps) {
  if (issues.isError) {
    return <ErrorState error={issues.error} onRetry={() => void issues.refetch()} />;
  }
  if (issues.isPending) {
    return <Loading label="Carregando pendências" h={220} />;
  }
  const rows = issues.data.items.filter((issue) => matchesSearch(issue, search));

  return (
    <Paper p="md">
      <Stack gap="md">
        <SearchInput
          label="Buscar pendência"
          placeholder="Buscar ativo ou data..."
          value={search}
          onChange={onSearchChange}
          maw={360}
        />
        <Table.ScrollContainer minWidth={640}>
          <Table verticalSpacing="sm" aria-label="Pendências">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Data</Table.Th>
                <Table.Th>Ativo</Table.Th>
                <Table.Th>Pendência</Table.Th>
                <Table.Th>Afetado desde</Table.Th>
                <Table.Th>
                  <VisuallyHidden>Ação</VisuallyHidden>
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={5}>
                    <Text size="sm" c="dimmed" ta="center" py="md">
                      Nenhuma pendência encontrada.
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : (
                rows.map((issue) => <IssueRow key={issue.id} issue={issue} />)
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        <Text size="sm" c="dimmed">
          {countLabel(rows.length, 'pendência encontrada', 'pendências encontradas')}
        </Text>
      </Stack>
    </Paper>
  );
}

function IssueRow({ issue }: { issue: Issue }) {
  const { icon, text } = ISSUE_TEXT[issue.issue_type];
  const action = issueAction(issue);
  return (
    <Table.Tr>
      {/*
        The date the user must act on (§10.3 "data necessária"): for a missing price, the date
        whose price is needed, which can precede the affected day (its D−1 price).
      */}
      <Table.Td>{formatDate(issue.required_price_date)}</Table.Td>
      <Table.Td fw={500}>
        <Figure text={issue.asset_code ?? UNAVAILABLE} />
      </Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          <Text span c="yellow.8" display="inline-flex" aria-hidden>
            {icon}
          </Text>
          <Text span size="sm">
            {text}
          </Text>
        </Group>
      </Table.Td>
      {/* The row's earliest affected date: rows come deduplicated (OQ-37). */}
      <Table.Td>{formatDate(issue.affected_date)}</Table.Td>
      <Table.Td ta="right">
        {action && (
          <Button component={Link} to={action.to} size="xs" variant="light">
            {action.label}
          </Button>
        )}
      </Table.Td>
    </Table.Tr>
  );
}
