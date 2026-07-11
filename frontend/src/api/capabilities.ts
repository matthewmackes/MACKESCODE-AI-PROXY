import { withConsoleToken } from './auth';
import { responseJsonOrThrow } from './errors';

export type Capability = {
  key: string;
  label: string;
  allowed: boolean;
  required_permission: string;
  category: string;
  reason: string;
};

export type CapabilitiesPayload = {
  actor: {
    id: string;
    roles: string[];
    permissions: string[];
    source: string;
    session_id?: string;
  };
  capabilities: Record<string, Capability>;
  allowed: string[];
};

export async function getCapabilities(): Promise<CapabilitiesPayload> {
  const response = await fetch(withConsoleToken('/v2/me/capabilities'));
  return responseJsonOrThrow<CapabilitiesPayload>(response, 'Capability request failed');
}
