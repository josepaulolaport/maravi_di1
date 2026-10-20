import { Text } from '@mantine/core';

import { chartTooltip } from '@/shared/ui/ChartTooltip';
import { SignedMoney } from '@/shared/ui/SignedMoney';

import { type ChartPoint, incompleteReason } from '../model/chartData';

/**
 * The day's range total, with the reason it adds nothing when it is not complete (OQ-41 item 5).
 */
export const PnlTooltip = chartTooltip<ChartPoint>((point) => {
  const reason = incompleteReason(point);
  return (
    <>
      <SignedMoney value={point.cumulativeText} size="sm" fw={500} />
      {reason !== null && (
        <Text size="xs" c="dimmed">
          {reason}
        </Text>
      )}
    </>
  );
});
