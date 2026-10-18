import { Stack } from '@mantine/core';
import { useState } from 'react';

import type { IsoDate, ProcessingRangeRequest, ProcessingRequest } from '@/api/contract';

import type { useProcessingRequests } from '../hooks/useProcessing';
import { CancelDialog } from './CancelDialog';
import { ConfirmProcessingModal } from './ConfirmProcessingModal';
import { HistoryTable } from './HistoryTable';
import { JobDetailsModal } from './JobDetailsModal';
import { isValidRange } from './RangeFields';
import { ReplaceDialog } from './ReplaceDialog';
import { RequestCard } from './RequestCard';

type Dialog = { kind: 'details' | 'cancel' | 'replace'; jobId: string } | null;

interface ProcessingTabProps {
  requests: ReturnType<typeof useProcessingRequests>;
  start: IsoDate | null;
  end: IsoDate | null;
  onStartChange: (date: IsoDate | null) => void;
  onEndChange: (date: IsoDate | null) => void;
  onRequestAgain: (start: IsoDate, end: IsoDate) => void;
  search: string;
  onSearchChange: (text: string) => void;
  today: IsoDate;
}

/**
 * Processamentos (§11.1, OQ-20): request an exact range, confirm it against the preview, and
 * follow, cancel or replace jobs in the history.
 */
export function ProcessingTab({
  requests,
  start,
  end,
  onStartChange,
  onEndChange,
  onRequestAgain,
  search,
  onSearchChange,
  today,
}: ProcessingTabProps) {
  const [confirming, setConfirming] = useState<ProcessingRangeRequest | null>(null);
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
  const requestAgain = (job: ProcessingRequest) => {
    setDialog(null);
    onRequestAgain(job.requested_start_date, job.requested_end_date);
  };

  return (
    <Stack gap="md">
      <RequestCard
        start={start}
        end={end}
        onStartChange={onStartChange}
        onEndChange={onEndChange}
        today={today}
        onRequest={() => {
          if (start && end && isValidRange(start, end)) {
            setConfirming({ start_date: start, end_date: end });
          }
        }}
      />
      <HistoryTable
        requests={requests}
        search={search}
        onSearchChange={onSearchChange}
        onDetails={open('details')}
        onCancel={open('cancel')}
        onReplace={open('replace')}
        onRequestAgain={requestAgain}
      />
      <ConfirmProcessingModal
        range={confirming}
        onClose={() => {
          setConfirming(null);
        }}
        onQueued={() => {
          setConfirming(null);
        }}
      />
      <JobDetailsModal
        job={jobFor('details')}
        onClose={close}
        onCancel={open('cancel')}
        onReplace={open('replace')}
        onRequestAgain={requestAgain}
      />
      <CancelDialog job={jobFor('cancel')} onClose={close} />
      <ReplaceDialog job={jobFor('replace')} onClose={close} today={today} />
    </Stack>
  );
}
