export type PlatformBranding = {
  developer: string;
  product: string;
  platform: string;
  brandName: string;
  consoleName: string;
  appIconUrl: string;
  sourceIconUrl: string;
};

export const PLATFORM_BRANDING: PlatformBranding = {
  developer: 'Matthew Mackes',
  product: 'MDE',
  platform: 'LLM-PROXY',
  brandName: 'MDE LLM-PROXY',
  consoleName: 'MDE LLM-PROXY Console v2',
  appIconUrl: '/brand/mde-app-icon.png',
  sourceIconUrl: 'https://github.com/matthewmackes/magic-mesh/blob/master/assets/brand/app-icon.png',
};

export function getPlatformBranding(): PlatformBranding {
  return PLATFORM_BRANDING;
}
