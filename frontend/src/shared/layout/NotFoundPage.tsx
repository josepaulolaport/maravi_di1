import { Anchor, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';

export function NotFoundPage() {
  return (
    <Stack gap="xs">
      <Title order={1} size="h3" fw={500}>
        Página não encontrada
      </Title>
      <Text c="dimmed" size="sm">
        O endereço acessado não existe.{' '}
        <Anchor component={Link} to="/">
          Voltar ao início
        </Anchor>
      </Text>
    </Stack>
  );
}
