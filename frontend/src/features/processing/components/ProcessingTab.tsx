import { Stack } from '@mantine/core';
import { useState } from 'react';

import type { ProcessingRequest } from '@/api/contract';
import {
  type ProcessingDraft,
  ProcessingRequestModal,
} from '@/shared/processing/ProcessingRequestModal';

import { useControlCenterParams } from '../hooks/useControlCenterParams';
import { useProcessingRequests } from '../hooks/useProcessing';
import type { RetryRequest } from '../model/jobStatus';
import { CancelDialog } from './CancelDialog';
import { HistoryTable } from './HistoryTable';
import { JobDetailsModal } from './JobDetailsModal';
import { RequestCard } from './RequestCard';

type Dialog = { kind: 'details' | 'cancel'; jobId: string } | null;

/**
 * Processamentos (§11.1, OQ-20): request an exact range, confirm it against the preview, and
 * follow, cancel or ask again for jobs in the history. The range, scope and search live in the
 * URL; the history is polled by the app-wide JobWatcher.
 */
export function ProcessingTab() {
  const params = useControlCenterParams();
  const requests = useProcessingRequests();
  const [draft, setDraft] = useState<ProcessingDraft | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  // Dialogs show the job as the history polls it, so its status and progress stay current.
  const jobFor = (kind: NonNullable<Dialog>['kind']): ProcessingRequest | null =>
    dialog?.kind === kind
      ? (requests.data?.items.find((job) => job.id === dialog.jobId) ?? null)
      : null;
  const open = (kind: NonNullable<Dialog>['kind']) => (job: ProcessingRequest) => {
    setDialog({ kind, jobId: job.id });
  };
  const close = () => {
    setDialog(null);
  };
  const requestAgain = (retry: RetryRequest) => {
    setDialog(null);
    // From where the run stopped, or the failed chain from its failed date, to the original end
    // (OQ-23 item 10, OQ-40 items 3 and 6).
    params.setRange(retry.start, retry.end, retry.scope);
  };

  return (
    <Stack gap="md">
      <RequestCard params={params} onRequest={setDraft} />
      <HistoryTable
        requests={requests}
        search={params.search}
        onSearchChange={params.setSearch}
        onDetails={open('details')}
        onCancel={open('cancel')}
        onRequestAgain={requestAgain}
      />
      <ProcessingRequestModal
        draft={draft}
        onClose={() => {
          setDraft(null);
        }}
        today={params.today}
        queuedMessage="Processamento colocado na fila."
      />
      <JobDetailsModal
        job={jobFor('details')}
        onClose={close}
        onCancel={open('cancel')}
        onRequestAgain={requestAgain}
      />
      <CancelDialog job={jobFor('cancel')} onClose={close} />
    </Stack>
  );
}
