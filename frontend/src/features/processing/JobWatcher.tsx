import { useJobWatcher } from './hooks/useProcessing';

/** Mounted once with the app shell: follows the jobs whichever screen is open (§10.4, §12). */
export function JobWatcher() {
  useJobWatcher();
  return null;
}
