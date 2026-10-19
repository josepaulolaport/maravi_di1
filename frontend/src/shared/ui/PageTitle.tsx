import { Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';

const APP = 'Maravi Backoffice';

/** The browser tab's title for a page: "Carteira · Maravi Backoffice". */
function usePageTitle(title: string) {
  useDocumentTitle(`${title} · ${APP}`);
}

/** A page's one `h1`, the same on every screen, and the browser tab's title. */
export function PageTitle({ children }: { children: string }) {
  usePageTitle(children);
  return (
    <Title order={1} size="h2" fw={500}>
      {children}
    </Title>
  );
}
