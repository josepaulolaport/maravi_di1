import { Button, Group, Skeleton, Stack } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useState } from 'react';
import { useParams, useSearchParams } from 'react-router';

import type { Instrument, IsoDate, ReferencePriceDay } from '@/api/contract';
import { assetLinks } from '@/app/paths';
import { formatDate, isIsoDate, todayInSaoPaulo } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';
import { StatusBadge } from '@/shared/ui/StatusBadge';

import { PageHeader } from './components/PageHeader';
import { PeriodPicker } from './components/PeriodPicker';
import { PriceCalendar } from './components/PriceCalendar';
import { calendarRows, calendarWindow, resolveRange } from './components/calendarData';
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
    return <Skeleton h={320} role="status" aria-label="Carregando contrato" />;
  }
  return <ContractBody key={instrument.data.id} instrument={instrument.data} />;
}

function ContractBody({ instrument }: { instrument: Instrument }) {
  const product = useProduct(instrument.product_id);
  const [params, setParams] = useSearchParams();
  const requested = params.get('registrar');
  // The period lives in the URL (`?inicio=&fim=`), like Lançamentos' range (§11.2).
  const { start, end } = resolveRange(
    { start: params.get('inicio'), end: params.get('fim'), register: requested },
    todayInSaoPaulo(),
    instrument.maturity_date,
  );
  const lastDay = resolveRange({}, todayInSaoPaulo(), instrument.maturity_date).end;
  const days = useReferencePriceDays(instrument.id, start, end);
  const setRange = (next: { start: IsoDate; end: IsoDate }) => {
    setParams(
      (current) => {
        current.set('inicio', next.start);
        current.set('fim', next.end);
        return current;
      },
      { replace: true },
    );
  };
  // The modal's date: the URL's `?registrar=` while it is there, otherwise UI state.
  const [modal, setModal] = useState<{ date: IsoDate | null; session: number }>({
    date: null,
    session: 0,
  });
  const modalDate = isIsoDate(requested) ? requested : modal.date;
  const openModal = (date: IsoDate) => {
    setModal((current) => ({ date, session: current.session + 1 }));
  };
  // One URL update: drop `?registrar=` and, when the saved date is outside the period, move
  // the period to end on it, so the new observation is always in view.
  const closeModal = (saved?: IsoDate) => {
    setModal((current) => ({ date: null, session: current.session + 1 }));
    const outside = saved !== undefined && (saved < start || saved > end);
    if (requested === null && !outside) return;
    setParams(
      (current) => {
        current.delete('registrar');
        // Without an explicit period, `?registrar=` chose the window; keep it in the URL so
        // closing the modal never moves the calendar away from that date.
        if (!current.has('inicio') || !current.has('fim')) {
          current.set('inicio', start);
          current.set('fim', end);
        }
        if (outside) {
          const moved = calendarWindow(saved, instrument.maturity_date);
          current.set('inicio', moved.start);
          current.set('fim', moved.end);
        }
        return current;
      },
      { replace: true },
    );
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
        <PeriodPicker start={start} end={end} maxDate={lastDay} onChange={setRange} />
      </Group>
      {days.isError ? (
        <ErrorState error={days.error} onRetry={() => void days.refetch()} />
      ) : days.isPending ? (
        <Stack gap="lg" aria-busy="true" aria-label="Carregando preços">
          <Skeleton h={240} />
          <Skeleton h={480} />
        </Stack>
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
      <PriceModal
        instrument={instrument}
        date={modalDate}
        session={modal.session}
        onClose={closeModal}
      />
      <RemovePriceModal
        day={removing}
        onClose={() => {
          setRemovingDate(null);
        }}
      />
    </Stack>
  );
}
