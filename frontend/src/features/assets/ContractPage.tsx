import { Button, Group, Stack } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useState } from 'react';
import { useParams } from 'react-router';

import { Loading } from '@/shared/ui/Loading';
import type { Instrument, IsoDate, ReferencePriceDay } from '@/api/contract';
import { assetLinks } from '@/app/paths';
import { formatDate } from '@/shared/format';
import { useToday } from '@/shared/hooks/useToday';
import { ErrorState } from '@/shared/ui/ErrorState';
import { PeriodPicker } from '@/shared/ui/PeriodPicker';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { dateParam, useQueryParams } from '@/shared/url/useQueryParams';

import { PageHeader } from './components/PageHeader';
import { PriceCalendar } from './components/PriceCalendar';
import { calendarRows, calendarWindow, lastDay, resolveRange } from './model/calendarData';
import { PriceModal } from './components/PriceModal';
import { PriceHistoryCard } from './components/PriceHistoryCard';
import { RemovePriceModal } from './components/RemovePriceModal';
import { useInstrument, useProduct } from './hooks/useAssets';
import { useReferencePriceDays } from './hooks/usePrices';

/**
 * A contract (spec §11.2, design 2:340): its reference-price history and calendar, where a
 * price for one date is registered, inspected, corrected or removed. There is no rate ↔ PU
 * calculator here (OQ-19 item 7). The period (`?inicio=&fim=`, default the last 30 days) drives
 * both the chart and the calendar. `?registrar=YYYY-MM-DD` opens the price modal on that date
 * ("Definir preço" from Pendências, §11.1).
 */
export function ContractPage() {
  const { instrumentId = '' } = useParams();
  const instrument = useInstrument(instrumentId);

  if (instrument.isError) {
    return <ErrorState error={instrument.error} onRetry={() => void instrument.refetch()} />;
  }
  if (instrument.isPending) {
    return <Loading label="Carregando contrato" h={320} />;
  }
  return <ContractBody key={instrument.data.id} instrument={instrument.data} />;
}

function ContractBody({ instrument }: { instrument: Instrument }) {
  const product = useProduct(instrument.product_id);
  // The period (`?inicio=&fim=`), like Lançamentos' range (§11.2), and `?registrar=`.
  const { values, set } = useQueryParams({
    inicio: dateParam(),
    fim: dateParam(),
    registrar: dateParam(),
  });
  const requested = values.registrar;
  const today = useToday();
  const { start, end } = resolveRange(
    { start: values.inicio, end: values.fim, register: requested },
    today,
    instrument.maturity_date,
  );
  const maxDate = lastDay(instrument.maturity_date, today);
  const days = useReferencePriceDays({ assetId: instrument.id, start, end });
  const setRange = (next: { start: IsoDate; end: IsoDate }) => {
    set({ inicio: next.start, fim: next.end }, { push: true });
  };
  // The modal's date: the URL's `?registrar=` while it is there, otherwise UI state.
  const [modalDate, setModalDate] = useState<IsoDate | null>(null);
  const openModal = (date: IsoDate) => {
    setModalDate(date);
  };
  // One URL update: drop `?registrar=` and, when the saved date is outside the period, move
  // the period to end on it, so the new observation is always in view. Without an explicit
  // period, `?registrar=` chose the window; it is kept in the URL, so closing the modal never
  // moves the calendar away from that date.
  const closeModal = (saved?: IsoDate) => {
    setModalDate(null);
    const outside = saved !== undefined && (saved < start || saved > end);
    if (requested === null && !outside) return;
    const period = outside ? calendarWindow(saved, instrument.maturity_date) : { start, end };
    set({ registrar: null, inicio: period.start, fim: period.end });
  };

  // Only the date is UI state; its observations are read from the query, so the modal always
  // lists what is current (also after a partial failure).
  const [removingDate, setRemovingDate] = useState<IsoDate | null>(null);
  const removing = days.data?.items.find((day) => day.reference_date === removingDate) ?? null;

  return (
    <Stack gap="lg">
      <PageHeader
        crumbs={[
          { label: 'Ativos', to: assetLinks.catalogue() },
          { label: instrument.product_code, to: assetLinks.product(instrument.product_id) },
          { label: instrument.code },
        ]}
        title={instrument.code}
        badge={
          <StatusBadge label={`Vencimento: ${formatDate(instrument.maturity_date)}`} color="gray" />
        }
        subtitle={product.data?.name}
        actions={
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => {
              openModal(end);
            }}
          >
            Registrar preço
          </Button>
        }
      />
      <Group>
        <PeriodPicker start={start} end={end} maxDate={maxDate} onChange={setRange} />
      </Group>
      {days.isError ? (
        <ErrorState error={days.error} onRetry={() => void days.refetch()} />
      ) : days.isPending ? (
        <Loading label="Carregando preços" h={[240, 480]} />
      ) : (
        <>
          <PriceHistoryCard items={days.data.items} start={start} end={end} />
          <PriceCalendar
            rows={calendarRows(days.data.items, start, end)}
            onRegister={openModal}
            onCorrect={openModal}
            onRemove={(day: ReferencePriceDay) => {
              setRemovingDate(day.reference_date);
            }}
          />
        </>
      )}
      <PriceModal instrument={instrument} date={requested ?? modalDate} onClose={closeModal} />
      <RemovePriceModal
        day={removing}
        onClose={() => {
          setRemovingDate(null);
        }}
      />
    </Stack>
  );
}
