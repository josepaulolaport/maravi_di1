import { Stack, Text, Title } from '@mantine/core';

interface PagePlaceholderProps {
  title: string;
}

/** Temporary body for a screen that is not built yet. */
export function PagePlaceholder({ title }: PagePlaceholderProps) {
  return (
    <Stack gap="xs">
      <Title order={1} size="h3" fw={500}>
        {title}
      </Title>
      <Text c="dimmed" size="sm">
        Tela em construção.
      </Text>
    </Stack>
  );
}
