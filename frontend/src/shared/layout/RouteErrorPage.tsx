import { Anchor, Center, Stack, Text, Title } from '@mantine/core';
import { Link, useRouteError } from 'react-router';

/** Shown when a screen throws while rendering: the app stays usable instead of going blank. */
export function RouteErrorPage() {
  const error = useRouteError();
  if (import.meta.env.DEV) console.error(error);

  return (
    <Center py="xl">
      <Stack gap="xs" align="center">
        <Title order={1} size="h3">
          Algo deu errado
        </Title>
        <Text c="dimmed" size="sm">
          Não foi possível exibir esta tela. Recarregue a página ou volte ao início.
        </Text>
        <Anchor component={Link} to="/" size="sm">
          Voltar ao início
        </Anchor>
      </Stack>
    </Center>
  );
}
