import { Button, Paper, SimpleGrid, Skeleton, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconPlus, IconSearch } from '@tabler/icons-react';
import { useState } from 'react';
import { useParams } from 'react-router';

import type { Product } from '@/api/contract';
import { assetLinks } from '@/app/paths';
import { formatMoney, UNAVAILABLE } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';
import { StatusBadge } from '@/shared/ui/StatusBadge';

import { ContractsTable } from './components/ContractsTable';
import { countLabel } from './components/countLabel';
import { NewContractDrawer } from './components/NewContractDrawer';
import { PageHeader } from './components/PageHeader';
import { useInstruments, useProduct, useSearchParam } from './hooks/useAssets';

/**
 * A product (spec §11.2, design 2:165): its shared futures specification (§3) and its
 * contracts, each with its latest reference observation next to its own date (OQ-19 item 5).
 */
export function ProductPage() {
  const { productId = '' } = useParams();
  const product = useProduct(productId);

  if (product.isError) {
    return <ErrorState error={product.error} onRetry={() => void product.refetch()} />;
  }
  if (product.isPending) {
    return <Skeleton h={320} role="status" aria-label="Carregando produto" />;
  }
  return <ProductBody key={product.data.id} product={product.data} />;
}

function ProductBody({ product }: { product: Product }) {
  const [text, setSearch, search] = useSearchParam();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const instruments = useInstruments(product.id, search);

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
              setDrawerOpen(true);
            }}
          >
            Novo contrato
          </Button>
        }
      />
      <SpecCard product={product} />
      <Paper>
        <Stack gap={0}>
          <Title order={2} size="h4" fw={500} p="md" pb={0}>
            Contratos
          </Title>
          <TextInput
            aria-label="Buscar contratos"
            placeholder="Buscar contrato por código..."
            leftSection={<IconSearch size={16} stroke={1.5} />}
            value={text}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
            }}
            m="md"
          />
          {instruments.isError ? (
            <ErrorState error={instruments.error} onRetry={() => void instruments.refetch()} />
          ) : instruments.isPending ? (
            <Skeleton h={160} m="md" role="status" aria-label="Carregando contratos" />
          ) : (
            <ContractsTable instruments={instruments.data.items} />
          )}
          <Text size="xs" c="dimmed" p="md">
            {countLabel(product.instrument_count, 'contrato cadastrado', 'contratos cadastrados')}
          </Text>
        </Stack>
      </Paper>
      <NewContractDrawer
        product={product}
        opened={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
        }}
      />
    </Stack>
  );
}

/** The product's shared specification (`asset.futures`, §3) and its pricing convention (§4.1). */
function SpecCard({ product }: { product: Product }) {
  const futures = product.futures;
  const specs = [
    {
      label: 'Valor de referência',
      value: futures ? formatMoney(futures.face_value) : UNAVAILABLE,
    },
    // DC/365 is the only convention (§4.1): no API field, fixed text.
    { label: 'Contagem de dias', value: 'Dias corridos / 365' },
    { label: 'Precificação', value: 'PU e taxa anual' },
  ];
  return (
    <Paper p="lg" role="region" aria-label="Especificações">
      <SimpleGrid cols={3}>
        {specs.map((spec) => (
          <Stack key={spec.label} gap={4}>
            <Text size="sm" c="dimmed">
              {spec.label}
            </Text>
            <Text fw={500}>{spec.value}</Text>
          </Stack>
        ))}
      </SimpleGrid>
    </Paper>
  );
}
