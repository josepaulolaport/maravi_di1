import {
  ActionIcon,
  Checkbox,
  Group,
  Menu,
  Table,
  Text,
  UnstyledButton,
  VisuallyHidden,
} from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconDots, IconTrash } from '@tabler/icons-react';

import {
  formatDate,
  formatPu,
  formatRate,
  formatSignedMoney,
  formatSignedQuantity,
  formatTime,
  UNAVAILABLE,
} from '@/shared/format';

import { ENTRY_TYPE_LABELS, type LedgerEntry, type SortDirection } from '../entries';

const recordedTime = new Intl.DateTimeFormat('pt-BR', {
  timeZone: 'America/Sao_Paulo',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/**
 * Names a row for screen readers and the delete dialogs, with enough of its figures to tell
 * same-day entries apart: "Venda DI1F28 -4 16/10/2026 15:00 PU 89.102,22",
 * "Retirada 16/10/2026 -R$ 50.000,00 registrada às 17:30". A cash movement has no effective
 * time (GAP-I-1), so the moment it was recorded (São Paulo) breaks ties.
 */
export function entryLabel(entry: LedgerEntry): string {
  const type = ENTRY_TYPE_LABELS[entry.entryType];
  if (entry.kind === 'cash') {
    const recorded = entry.entryType === 'DEPOSIT' ? 'registrado' : 'registrada';
    const at = recordedTime.format(new Date(entry.createdAt));
    return `${type} ${formatDate(entry.date)} ${formatSignedMoney(entry.signedAmount)} ${recorded} às ${at}`;
  }
  const quantity = formatSignedQuantity(entry.signedQuantity);
  const when = `${formatDate(entry.date)} ${formatTime(entry.time)}`;
  return `${type} ${entry.assetCode} ${quantity} ${when} PU ${formatPu(entry.pu)}`;
}

const dash = <span title="Não se aplica">{UNAVAILABLE}</span>;
const unknownType = <span title="Indisponível">{UNAVAILABLE}</span>;

interface EntriesTableProps {
  entries: LedgerEntry[];
  /** Instrument type code → its name from the API (e.g. FUTURE → Futuros); a code is never shown. */
  instrumentTypeNames: Map<string, string>;
  sort: SortDirection;
  onToggleSort: () => void;
  selected: Set<string>;
  onToggle: (key: string) => void;
  onToggleAll: () => void;
  onDelete: (entry: LedgerEntry) => void;
}

/**
 * The columns of §11.3: instrument type ("Futuros", "Caixa") and entry type (Compra, Venda,
 * Aporte, Retirada) are separate. A trade shows PU and rate (the typed one and the one the
 * backend computed, OQ-19 item 7); a cash movement has neither, nor an asset or quantity.
 */
export function EntriesTable({
  entries,
  instrumentTypeNames,
  sort,
  onToggleSort,
  selected,
  onToggle,
  onToggleAll,
  onDelete,
}: EntriesTableProps) {
  const selectedCount = entries.filter((e) => selected.has(e.key)).length;
  const allSelected = entries.length > 0 && selectedCount === entries.length;

  return (
    <Table.ScrollContainer minWidth={1040}>
      <Table highlightOnHover verticalSpacing="sm" aria-label="Lançamentos">
        <Table.Thead bg="gray.0">
          <Table.Tr>
            <Table.Th w={40}>
              <Checkbox
                aria-label="Selecionar todos"
                checked={allSelected}
                indeterminate={selectedCount > 0 && !allSelected}
                disabled={entries.length === 0}
                onChange={onToggleAll}
              />
            </Table.Th>
            <Table.Th
              style={{ whiteSpace: 'nowrap' }}
              aria-sort={sort === 'asc' ? 'ascending' : 'descending'}
            >
              <UnstyledButton onClick={onToggleSort} fz="sm" fw={400} c="dimmed">
                <Group gap={4} wrap="nowrap">
                  Data e hora
                  {sort === 'asc' ? (
                    <IconArrowUp size={14} stroke={1.5} aria-hidden />
                  ) : (
                    <IconArrowDown size={14} stroke={1.5} aria-hidden />
                  )}
                </Group>
              </UnstyledButton>
            </Table.Th>
            {['Tipo de ativo', 'Tipo', 'Ativo'].map((label) => (
              <Table.Th key={label} fw={400} c="dimmed">
                {label}
              </Table.Th>
            ))}
            {['Qtd.', 'PU', 'Taxa', 'Valor financeiro'].map((label) => (
              <Table.Th key={label} ta="right" fw={400} c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                {label}
              </Table.Th>
            ))}
            <Table.Th w={48}>
              <VisuallyHidden>Ações</VisuallyHidden>
            </Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {entries.map((entry) => {
            const label = entryLabel(entry);
            const trade = entry.kind === 'trade' ? entry : null;
            return (
              <Table.Tr
                key={entry.key}
                {...(selected.has(entry.key) ? { bg: 'var(--mantine-primary-color-light)' } : {})}
              >
                <Table.Td>
                  <Checkbox
                    aria-label={`Selecionar ${label}`}
                    checked={selected.has(entry.key)}
                    onChange={() => {
                      onToggle(entry.key);
                    }}
                  />
                </Table.Td>
                <Table.Td style={{ whiteSpace: 'nowrap' }}>
                  {trade
                    ? `${formatDate(trade.date)} ${formatTime(trade.time)}`
                    : formatDate(entry.date)}
                </Table.Td>
                <Table.Td>
                  {trade
                    ? (instrumentTypeNames.get(trade.instrumentTypeCode) ?? unknownType)
                    : 'Caixa'}
                </Table.Td>
                <Table.Td>{ENTRY_TYPE_LABELS[entry.entryType]}</Table.Td>
                <Table.Td>
                  {trade ? (
                    <Text inherit fw={500}>
                      {trade.assetCode}
                    </Text>
                  ) : (
                    dash
                  )}
                </Table.Td>
                <Table.Td ta="right">
                  {trade ? formatSignedQuantity(trade.signedQuantity) : dash}
                </Table.Td>
                <Table.Td ta="right">{trade ? formatPu(trade.pu) : dash}</Table.Td>
                <Table.Td ta="right">{trade ? formatRate(trade.rate) : dash}</Table.Td>
                <Table.Td ta="right" style={{ whiteSpace: 'nowrap' }}>
                  {formatSignedMoney(entry.signedAmount)}
                </Table.Td>
                <Table.Td>
                  <Menu position="bottom-end" withinPortal>
                    <Menu.Target>
                      <ActionIcon variant="subtle" color="gray" aria-label={`Ações de ${label}`}>
                        <IconDots size={16} stroke={1.5} />
                      </ActionIcon>
                    </Menu.Target>
                    <Menu.Dropdown>
                      <Menu.Item
                        color="red"
                        leftSection={<IconTrash size={14} stroke={1.5} />}
                        onClick={() => {
                          onDelete(entry);
                        }}
                      >
                        Excluir
                      </Menu.Item>
                    </Menu.Dropdown>
                  </Menu>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
