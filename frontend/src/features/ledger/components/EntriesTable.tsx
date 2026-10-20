import {
  ActionIcon,
  Checkbox,
  Group,
  Menu,
  Table,
  Text,
  Tooltip,
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

import table from '@/shared/ui/table.module.css';

import { ENTRY_TYPE_LABELS, type LedgerEntry, type SortDirection } from '../entries';

/**
 * Names a row for screen readers and the delete dialogs, with enough of its figures to tell
 * same-day entries apart: "Venda DI1F28 -4 16/10/2026 15:00 PU 89.102,22",
 * "Retirada 16/10/2026 17:30 -R$ 50.000,00", "Aporte 14/10/2026 09:00 +R$ 1.500.000,00 (Aporte
 * inicial)" for a cash entry with a description (OQ-51).
 */
export function entryLabel(entry: LedgerEntry): string {
  const type = ENTRY_TYPE_LABELS[entry.entryType];
  const when = `${formatDate(entry.date)} ${formatTime(entry.time)}`;
  if (entry.kind === 'cash') {
    const label = `${type} ${when} ${formatSignedMoney(entry.signedAmount)}`;
    return entry.description ? `${label} (${entry.description})` : label;
  }
  const quantity = formatSignedQuantity(entry.signedQuantity);
  return `${type} ${entry.assetCode} ${quantity} ${when} PU ${formatPu(entry.pu)}`;
}

/** The Financeiro column is the entry's cash effect (`cash_amount`), not a market value. */
const CASH_EFFECT_HINT =
  'Efeito no caixa: compra negativa, venda positiva; aporte positivo, retirada negativa.';

const dash = <span title="Não se aplica">{UNAVAILABLE}</span>;
const unknownType = <span title="Indisponível">{UNAVAILABLE}</span>;
const noDescription = <span title="Sem descrição">{UNAVAILABLE}</span>;

/** A cash entry's description (OQ-51): one line, cut with an ellipsis, in full in a tooltip. */
function Description({ text }: { text: string | null }) {
  if (!text) return noDescription;
  return (
    <Tooltip
      label={text}
      multiline
      maw={360}
      events={{ hover: true, focus: true, touch: true }}
      withinPortal
    >
      <Text inherit truncate="end" maw={220} tabIndex={0}>
        {text}
      </Text>
    </Tooltip>
  );
}

interface EntriesTableProps {
  entries: LedgerEntry[];
  /** Instrument type code → its name from the API (e.g. FUTURE → Futuros); a code is never shown. */
  instrumentTypeNames: Map<string, string>;
  sort: SortDirection;
  onToggleSort: () => void;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  onDelete: (entry: LedgerEntry) => void;
}

/**
 * The columns of §11.3: instrument type ("Futuros", "Caixa") and entry type (Compra, Venda,
 * Aporte, Retirada) are separate. A trade shows PU and rate (the typed one and the one the
 * backend computed, OQ-19 item 7); a cash entry has neither, nor an asset or quantity, but may
 * have a description (OQ-51), which a trade never has.
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
  const selectedCount = entries.filter((e) => selected.has(e.id)).length;
  const allSelected = entries.length > 0 && selectedCount === entries.length;

  return (
    <Table.ScrollContainer minWidth={1200}>
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
              className={table.nowrap}
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
            {['Tipo de ativo', 'Tipo', 'Ativo', 'Descrição'].map((label) => (
              <Table.Th key={label} fw={400} c="dimmed">
                {label}
              </Table.Th>
            ))}
            {['Qtd.', 'PU', 'Taxa'].map((label) => (
              <Table.Th key={label} ta="right" fw={400} c="dimmed" className={table.nowrap}>
                {label}
              </Table.Th>
            ))}
            <Table.Th ta="right" fw={400} c="dimmed" className={table.nowrap}>
              <Tooltip label={CASH_EFFECT_HINT} events={{ hover: true, focus: true, touch: true }}>
                <Text component="span" inherit tabIndex={0} td="underline dotted">
                  Financeiro
                </Text>
              </Tooltip>
            </Table.Th>
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
                key={entry.id}
                {...(selected.has(entry.id) ? { bg: 'var(--mantine-primary-color-light)' } : {})}
              >
                <Table.Td>
                  <Checkbox
                    aria-label={`Selecionar ${label}`}
                    checked={selected.has(entry.id)}
                    onChange={() => {
                      onToggle(entry.id);
                    }}
                  />
                </Table.Td>
                <Table.Td className={table.nowrap}>
                  {`${formatDate(entry.date)} ${formatTime(entry.time)}`}
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
                <Table.Td>
                  {entry.kind === 'cash' ? <Description text={entry.description} /> : dash}
                </Table.Td>
                <Table.Td ta="right">
                  {trade ? formatSignedQuantity(trade.signedQuantity) : dash}
                </Table.Td>
                <Table.Td ta="right">{trade ? formatPu(trade.pu) : dash}</Table.Td>
                <Table.Td ta="right">{trade ? formatRate(trade.rate) : dash}</Table.Td>
                <Table.Td ta="right" className={table.nowrap}>
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
