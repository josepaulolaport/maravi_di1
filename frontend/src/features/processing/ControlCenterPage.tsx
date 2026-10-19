import { Badge, Stack, Tabs, VisuallyHidden } from '@mantine/core';

import { PageTitle } from '@/shared/ui/PageTitle';
import { countLabel, formatQuantity } from '@/shared/format';

import { IssuesTab } from './components/IssuesTab';
import { ProcessingTab } from './components/ProcessingTab';
import { type ControlCenterTab, useControlCenterParams } from './hooks/useControlCenterParams';
import { useIssues, useProcessingRequests } from './hooks/useProcessing';

/**
 * Central de Controle (spec §11.1): Pendências and Processamentos, with the tab, the range
 * and the search in the URL. No financial KPIs here.
 */
export function ControlCenterPage() {
  const params = useControlCenterParams();
  const issues = useIssues();
  // Read here, not in the tab, so a job followed from Processamentos is still polled, and
  // its end still refreshes the results, while Pendências is open.
  const requests = useProcessingRequests();

  return (
    <Stack gap="md">
      <PageTitle>Central de Controle</PageTitle>
      <Tabs
        value={params.tab}
        onChange={(value) => {
          if (value) params.setTab(value as ControlCenterTab);
        }}
        keepMounted={false}
      >
        <Tabs.List mb="md">
          <Tabs.Tab
            value="pendencias"
            rightSection={
              issues.data && (
                // Read once, in words, by the hidden text below; the badge is for the eye.
                <Badge size="sm" variant="light" circle aria-hidden>
                  {formatQuantity(issues.data.items.length)}
                </Badge>
              )
            }
          >
            Pendências
            {issues.data && (
              <VisuallyHidden>
                {`, ${countLabel(issues.data.items.length, 'pendência', 'pendências')}`}
              </VisuallyHidden>
            )}
          </Tabs.Tab>
          <Tabs.Tab value="processamentos">Processamentos</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="pendencias">
          <IssuesTab issues={issues} search={params.search} onSearchChange={params.setSearch} />
        </Tabs.Panel>
        <Tabs.Panel value="processamentos">
          <ProcessingTab
            requests={requests}
            start={params.start}
            end={params.end}
            onStartChange={params.setStart}
            onEndChange={params.setEnd}
            scope={params.scope}
            onScopeChange={params.setScope}
            onRequestAgain={params.setRange}
            search={params.search}
            onSearchChange={params.setSearch}
            today={params.today}
          />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
