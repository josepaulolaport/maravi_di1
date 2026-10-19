import { useSearchParams } from 'react-router';

import type { IsoDate } from '@/api/contract';
import { isIsoDate, todayInSaoPaulo } from '@/shared/format';

// Central de Controle keeps its URL state in the query string (frontend/CLAUDE.md), with the
// keys `controlCenterLinks` builds: `tab`, `inicio`, `fim`, plus `busca` for the search.

export type ControlCenterTab = 'pendencias' | 'processamentos';

const TABS: readonly ControlCenterTab[] = ['pendencias', 'processamentos'];

/** A date from the URL, or `null` when missing, invalid or after today (OQ-14). */
function readDate(value: string | null, today: IsoDate): IsoDate | null {
  return isIsoDate(value) && value <= today ? value : null;
}

export function useControlCenterParams() {
  const [params, setParams] = useSearchParams();
  const today = todayInSaoPaulo();
  const requestedTab = params.get('tab');
  const tab: ControlCenterTab = TABS.find((t) => t === requestedTab) ?? 'pendencias';

  const update = (changes: Record<string, string | null>) => {
    setParams(
      (current) => {
        for (const [key, value] of Object.entries(changes)) {
          if (value) current.set(key, value);
          else current.delete(key);
        }
        return current;
      },
      { replace: true },
    );
  };

  return {
    tab,
    /** A new tab starts with an empty search. */
    setTab: (next: ControlCenterTab) => {
      update({ tab: next, busca: null });
    },
    start: readDate(params.get('inicio'), today),
    end: readDate(params.get('fim'), today),
    setStart: (date: IsoDate | null) => {
      update({ inicio: date });
    },
    setEnd: (date: IsoDate | null) => {
      update({ fim: date });
    },
    /** Prefills the request form with a range ("Solicitar novo processamento", OQ-20). */
    setRange: (start: IsoDate, end: IsoDate) => {
      update({ tab: 'processamentos', inicio: start, fim: end });
    },
    search: params.get('busca') ?? '',
    setSearch: (text: string) => {
      update({ busca: text });
    },
    today,
  };
}
