import { ActionIcon, Table, Text } from '@mantine/core';
import { IconChevronRight } from '@tabler/icons-react';
import { Link } from 'react-router';

import type { Product } from '@/api/contract';
import { assetLinks } from '@/app/paths';

import { countLabel } from '@/shared/format';

/** Catalogue rows (§11.2): código, produto, classe, contratos; each opens its product. */
export function ProductsTable({ products }: { products: Product[] }) {
  return (
    <>
      <Table.ScrollContainer minWidth={640}>
        <Table aria-label="Produtos" highlightOnHover verticalSpacing="sm" horizontalSpacing="md">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Código</Table.Th>
              <Table.Th>Produto</Table.Th>
              <Table.Th>Classe</Table.Th>
              <Table.Th ta="right">Contratos</Table.Th>
              <Table.Th w={48} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {products.map((product) => (
              <Table.Tr key={product.id}>
                <Table.Td>
                  <Text inherit fw={500}>
                    {product.code}
                  </Text>
                </Table.Td>
                <Table.Td>{product.name}</Table.Td>
                <Table.Td>{product.asset_class.name}</Table.Td>
                <Table.Td ta="right">{product.instrument_count}</Table.Td>
                <Table.Td>
                  <ActionIcon
                    component={Link}
                    to={assetLinks.product(product.id)}
                    variant="subtle"
                    color="gray"
                    aria-label={`Abrir produto ${product.code}`}
                  >
                    <IconChevronRight size={16} stroke={1.5} />
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Text size="xs" c="dimmed" p="md">
        {countLabel(products.length, 'produto encontrado', 'produtos encontrados')}
      </Text>
    </>
  );
}
