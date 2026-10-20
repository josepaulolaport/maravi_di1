import {
  Badge,
  Group,
  Paper,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
  UnstyledButton,
  VisuallyHidden,
} from '@mantine/core';
import { IconArrowDown, IconArrowsSort, IconArrowUp } from '@tabler/icons-react';
import type { ReactNode } from 'react';

import table from '@/shared/ui/table.module.css';
import type { PositionRow } from '@/api/contract';
import {
  countLabel,
  formatDate,
  formatMoney,
  formatPu,
  formatQuantity,
  formatRate,
} from '@/shared/format';
import { SearchInput } from '@/shared/ui/SearchInput';
import { Figure } from '@/shared/ui/Figure';
import { SignedMoney } from '@/shared/ui/SignedMoney';

import type { PortfolioParams } from '../hooks/usePortfolio';
import { type Sort, type SortKey, sortPositions } from '../model/sortPositions';

interface Column {
  key: SortKey;
  label: string;
  numeric: boolean;
  render: (row: PositionRow) => ReactNode;
}

const PRICE_CHANGED = 'Preço alterado após o processamento — reprocesse';

// The columns of §11.4, in the design's order. No realized/unrealized P&L, no cumulative P&L
// per asset, and cash is not a row (D1, OQ-19 item 1).
const columns: Column[] = [
  {
    key: 'asset_code',
    label: 'Ativo',
    numeric: false,
    render: (row) => (
      // The badge sits under the code: the column stays narrow and the badge is never cut.
      <Stack gap={2} align="flex-start">
        <Text span inherit fw={500}>
          {row.asset_code}
        </Text>
        {row.valuation_status === 'MISSING' ? (
          <Badge color="red" variant="light" size="sm" className={table.badge}>
            Sem preço
          </Badge>
        ) : (
          row.pnl_status === 'MISSING' && (
            <Badge color="orange" variant="light" size="sm" className={table.badge}>
              P&L indisponível
            </Badge>
          )
        )}
        {row.reference_price_changed && (
          // A10: the figures come from the price the run read; the shown price is newer.
          <Tooltip label={PRICE_CHANGED} withArrow>
            <Badge color="yellow" variant="light" size="sm" className={table.badge} tabIndex={0}>
              Preço alterado
              <VisuallyHidden> após o processamento — reprocesse</VisuallyHidden>
            </Badge>
          </Tooltip>
        )}
      </Stack>
    ),
  },
  {
    key: 'maturity_date',
    label: 'Vencimento',
    numeric: false,
    render: (r) => formatDate(r.maturity_date),
  },
  { key: 'quantity', label: 'Qtd.', numeric: true, render: (r) => formatQuantity(r.quantity) },
  {
    key: 'average_entry_pu',
    label: 'PU médio',
    numeric: true,
    render: (r) => <Figure text={formatPu(r.average_entry_pu)} />,
  },
  {
    key: 'average_entry_rate',
    label: 'Taxa média',
    numeric: true,
    render: (r) => <Figure text={formatRate(r.average_entry_rate)} />,
  },
  {
    key: 'reference_pu',
    label: 'PU ref.',
    numeric: true,
    render: (r) => <Figure text={formatPu(r.reference_pu)} />,
  },
  {
    key: 'reference_rate',
    label: 'Taxa ref.',
    numeric: true,
    render: (r) => <Figure text={formatRate(r.reference_rate)} />,
  },
  {
    key: 'financial_total',
    label: 'Valor de mercado',
    numeric: true,
    render: (r) => <Figure text={formatMoney(r.financial_total)} />,
  },
  {
    key: 'position_pnl',
    label: 'P&L posições',
    numeric: true,
    render: (r) => <SignedMoney value={r.position_pnl} />,
  },
  {
    key: 'trades_pnl',
    label: 'P&L operações',
    numeric: true,
    render: (r) => <SignedMoney value={r.trades_pnl} />,
  },
];

function SortIcon({ active, direction }: { active: boolean; direction: Sort['direction'] }) {
  if (!active) return <IconArrowsSort size={14} stroke={1.5} aria-hidden />;
  return direction === 'asc' ? (
    <IconArrowUp size={14} stroke={1.5} aria-hidden />
  ) : (
    <IconArrowDown size={14} stroke={1.5} aria-hidden />
  );
}

interface PositionsTableProps {
  rows: PositionRow[];
  /** The search and order, in the URL (`usePortfolioParams`). */
  view: Pick<PortfolioParams, 'search' | 'setSearch' | 'sort' | 'setSort'>;
}

export function PositionsTable({ rows, view }: PositionsTableProps) {
  const { search, setSearch, sort, setSort } = view;

  const needle = search.trim().toLocaleUpperCase('pt-BR');
  const visible = sortPositions(
    rows.filter((row) => row.asset_code.toLocaleUpperCase('pt-BR').includes(needle)),
    sort,
  );

  const toggleSort = (key: SortKey) => {
    setSort(
      sort.key === key
        ? { key, direction: sort.direction === 'asc' ? 'desc' : 'asc' }
        : { key, direction: 'asc' },
    );
  };

  return (
    <Paper>
      <Group justify="space-between" p="md">
        <Title order={2} size="h5" fw={500}>
          Posições
        </Title>
        <SearchInput
          label="Buscar ativo"
          placeholder="Buscar ativo..."
          value={search}
          onChange={setSearch}
          w={260}
        />
      </Group>
      <Table.ScrollContainer minWidth={980}>
        <Table highlightOnHover verticalSpacing="sm" aria-label="Posições">
          <Table.Thead bg="gray.0">
            <Table.Tr>
              {columns.map((column) => {
                const active = sort.key === column.key;
                return (
                  <Table.Th
                    key={column.key}
                    ta={column.numeric ? 'right' : 'left'}
                    className={table.nowrap}
                    aria-sort={
                      active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'
                    }
                  >
                    <UnstyledButton
                      onClick={() => {
                        toggleSort(column.key);
                      }}
                      fz="sm"
                      fw={400}
                      c="dimmed"
                    >
                      <Group
                        gap={4}
                        wrap="nowrap"
                        justify={column.numeric ? 'flex-end' : 'flex-start'}
                      >
                        {column.label}
                        <SortIcon active={active} direction={sort.direction} />
                      </Group>
                    </UnstyledButton>
                  </Table.Th>
                );
              })}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visible.map((row) => (
              <Table.Tr key={row.asset_id}>
                {columns.map((column) => (
                  <Table.Td key={column.key} ta={column.numeric ? 'right' : 'left'}>
                    {column.render(row)}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {visible.length === 0 && (
        <Text size="sm" c="dimmed" ta="center" py="xl">
          {rows.length === 0 ? 'Nenhuma posição nesta data.' : 'Nenhum ativo encontrado.'}
        </Text>
      )}
      <VisuallyHidden role="status">
        {countLabel(visible.length, 'posição exibida', 'posições exibidas')}
      </VisuallyHidden>
    </Paper>
  );
}
