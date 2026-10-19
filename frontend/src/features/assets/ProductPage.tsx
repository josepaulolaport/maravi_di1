import { Button, Group, Paper, Stack, Text, Title } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useState } from 'react';
import { useParams } from 'react-router';

import { SearchInput } from '@/shared/ui/SearchInput';
import { Loading } from '@/shared/ui/Loading';
import type { Instrument, IsoDate, Product } from '@/api/contract';
import { assetLinks } from '@/app/paths';
import { ErrorState } from '@/shared/ui/ErrorState';
import { StatusBadge } from '@/shared/ui/StatusBadge';

import { ContractsTable } from './components/ContractsTable';
import { countLabel, todayInSaoPaulo } from '@/shared/format';
import { NewContractModal } from './components/NewContractModal';
import { lastDay } from './components/calendarData';
import { PageHeader } from './components/PageHeader';
import { PriceModal } from './components/PriceModal';
import { RemovePriceByDateModal } from './components/RemovePriceByDateModal';
import { useInstruments, useProduct, useSearchParam } from './hooks/useAssets';

/**
 * A product (spec §11.2, design 2:165): its contracts, each with its latest reference
 * observation next to its own date (OQ-19 item 5). No specification card (user, 2026-10-18).
 * A price is registered or removed from the list too (user, 2026-10-19): "Registrar preço" above
 * it, and each row's menu.
 */
export function ProductPage() {
  const { productId = '' } = useParams();
  const product = useProduct(productId);

  if (product.isError) {
    return <ErrorState error={product.error} onRetry={() => void product.refetch()} />;
  }
  if (product.isPending) {
    return <Loading label="Carregando produto" h={320} />;
  }
  return <ProductBody key={product.data.id} product={product.data} />;
}

function ProductBody({ product }: { product: Product }) {
  const [search, setSearch] = useSearchParam();
  const [modalOpen, setModalOpen] = useState(false);
  const instruments = useInstruments(product.id, search);
  // Every contract of the product, whatever the search, for the price form's select.
  const allInstruments = useInstruments(product.id, '');
  const [price, setPrice] = useState<{
    instrument: Instrument | null;
    date: IsoDate | null;
    session: number;
  }>({ instrument: null, date: null, session: 0 });
  // The form opens on today, or on a matured contract's last day (OQ-1).
  const openPrice = (instrument: Instrument | null) => {
    const date = lastDay(instrument, todayInSaoPaulo());
    setPrice((current) => ({ instrument, date, session: current.session + 1 }));
  };
  const [removing, setRemoving] = useState<Instrument | null>(null);

  return (
    <Stack gap="lg">
      <PageHeader
        crumbs={[{ label: 'Ativos', to: assetLinks.catalogue() }, { label: product.code }]}
        title={product.code}
        badge={<StatusBadge label={product.asset_class.name} color="gray" />}
        subtitle={product.name}
        actions={
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => {
              setModalOpen(true);
            }}
          >
            Novo contrato
          </Button>
        }
      />
      <Paper>
        <Stack gap={0}>
          <Group justify="space-between" p="md" pb={0}>
            <Title order={2} size="h4" fw={500}>
              Contratos
            </Title>
            <Button
              variant="light"
              leftSection={<IconPlus size={16} />}
              onClick={() => {
                openPrice(null);
              }}
            >
              Registrar preço
            </Button>
          </Group>
          <SearchInput
            label="Buscar contratos"
            placeholder="Buscar contrato por código..."
            value={search}
            onChange={setSearch}
            m="md"
          />
          {instruments.isError ? (
            <ErrorState error={instruments.error} onRetry={() => void instruments.refetch()} />
          ) : instruments.isPending ? (
            <Loading label="Carregando contratos" h={160} m="md" />
          ) : (
            <ContractsTable
              instruments={instruments.data.items}
              onRegisterPrice={openPrice}
              onRemovePrice={setRemoving}
            />
          )}
          <Text size="xs" c="dimmed" p="md">
            {countLabel(product.instrument_count, 'contrato cadastrado', 'contratos cadastrados')}
          </Text>
        </Stack>
      </Paper>
      <NewContractModal
        product={product}
        opened={modalOpen}
        onClose={() => {
          setModalOpen(false);
        }}
      />
      <PriceModal
        instrument={price.instrument}
        contracts={allInstruments.data?.items ?? (price.instrument ? [price.instrument] : [])}
        contractsStatus={allInstruments.status}
        date={price.date}
        session={price.session}
        onClose={() => {
          setPrice((current) => ({ ...current, date: null }));
        }}
      />
      <RemovePriceByDateModal
        instrument={removing}
        onClose={() => {
          setRemoving(null);
        }}
      />
    </Stack>
  );
}
