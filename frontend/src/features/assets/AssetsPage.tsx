import { Paper, Skeleton, Stack, Tabs, Text, TextInput, Title } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useSearchParams } from 'react-router';

import { ErrorState } from '@/shared/ui/ErrorState';

import { ProductsTable } from './components/ProductsTable';
import { useInstrumentTypes, useProducts, useSearchParam } from './hooks/useAssets';

/**
 * Ativos catalogue (spec §11.2, design 2:2): instrument types as tabs, then the products of the
 * selected type with their class. Only what the API returns (OQ-19 item 4). The tab
 * (`?tipo=`) and the search (`?busca=`) live in the URL.
 */
export function AssetsPage() {
  const types = useInstrumentTypes();
  const [params, setParams] = useSearchParams();
  const [text, setSearch, search] = useSearchParam();

  const items = types.data?.items ?? [];
  const requested = params.get('tipo');
  const selected = items.find((t) => t.code === requested)?.code ?? items[0]?.code;
  const products = useProducts(selected, search);

  const selectType = (code: string | null) => {
    if (!code) return;
    setParams(
      (current) => {
        current.set('tipo', code);
        return current;
      },
      { replace: true },
    );
  };

  return (
    <Stack gap="md">
      <Title order={1} size="h2" fw={500}>
        Ativos
      </Title>
      {types.isError ? (
        <ErrorState error={types.error} onRetry={() => void types.refetch()} />
      ) : types.isPending ? (
        <Skeleton h={240} role="status" aria-label="Carregando catálogo" />
      ) : items.length === 0 ? (
        <Text size="sm" c="dimmed">
          Nenhum tipo de instrumento cadastrado.
        </Text>
      ) : (
        <Tabs value={selected ?? null} onChange={selectType}>
          <Tabs.List>
            {items.map((type) => (
              <Tabs.Tab key={type.code} value={type.code}>
                {type.name}
              </Tabs.Tab>
            ))}
          </Tabs.List>
          {items.map((type) => (
            <Tabs.Panel key={type.code} value={type.code} pt="md">
              {type.code === selected && (
                <Paper>
                  <TextInput
                    aria-label="Buscar produtos"
                    placeholder="Buscar por código, produto ou classe..."
                    leftSection={<IconSearch size={16} stroke={1.5} />}
                    value={text}
                    onChange={(event) => {
                      setSearch(event.currentTarget.value);
                    }}
                    m="md"
                  />
                  {products.isError ? (
                    <ErrorState error={products.error} onRetry={() => void products.refetch()} />
                  ) : products.isPending ? (
                    <Skeleton h={120} m="md" role="status" aria-label="Carregando produtos" />
                  ) : (
                    <ProductsTable products={products.data.items} />
                  )}
                </Paper>
              )}
            </Tabs.Panel>
          ))}
        </Tabs>
      )}
    </Stack>
  );
}
