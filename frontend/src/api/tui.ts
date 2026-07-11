import { withConsoleToken } from './auth';
import { responseJsonOrThrow } from './errors';

export type TuiStatus = {
  running: boolean;
  pid?: number | null;
  started_at: number;
  command: string[];
  lease: {
    holder: string;
    acquired_at: number;
    active: boolean;
  };
};

export async function getTuiStatus(): Promise<TuiStatus> {
  const response = await fetch(withConsoleToken('/v2/console/tui/status'));
  return responseJsonOrThrow<TuiStatus>(response, 'TUI status failed');
}

export async function acquireTuiControl(clientId: string): Promise<TuiStatus['lease']> {
  const response = await fetch(withConsoleToken('/v2/console/tui/control/acquire'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ client_id: clientId })
  });
  const payload = await responseJsonOrThrow<{ lease: TuiStatus['lease'] }>(response, 'TUI control acquire failed');
  return payload.lease;
}

export async function releaseTuiControl(clientId: string): Promise<TuiStatus['lease']> {
  const response = await fetch(withConsoleToken('/v2/console/tui/control/release'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ client_id: clientId })
  });
  const payload = await responseJsonOrThrow<{ lease: TuiStatus['lease'] }>(response, 'TUI control release failed');
  return payload.lease;
}
