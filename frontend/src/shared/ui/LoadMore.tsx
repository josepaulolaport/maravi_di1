import { Button, Group } from '@mantine/core';

interface LoadMoreProps {
  /** The list has a next page (`next_cursor` is not `null`). */
  hasMore: boolean;
  loading: boolean;
  onLoad: () => void;
}

/** "Carregar mais" under a keyset-paginated list (P21): reads the next page, if there is one. */
export function LoadMore({ hasMore, loading, onLoad }: LoadMoreProps) {
  if (!hasMore) return null;
  return (
    <Group justify="center" p="md">
      <Button variant="default" loading={loading} onClick={onLoad}>
        Carregar mais
      </Button>
    </Group>
  );
}
