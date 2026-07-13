import alibabaCloudMark from 'simple-icons/icons/alibabacloud.svg?raw';
import anthropicMark from 'simple-icons/icons/anthropic.svg?raw';
import deepseekMark from 'simple-icons/icons/deepseek.svg?raw';
import digitalOceanMark from 'simple-icons/icons/digitalocean.svg?raw';
import googleMark from 'simple-icons/icons/google.svg?raw';
import metaMark from 'simple-icons/icons/meta.svg?raw';
import minimaxMark from 'simple-icons/icons/minimax.svg?raw';
import mistralMark from 'simple-icons/icons/mistralai.svg?raw';
import moonshotMark from 'simple-icons/icons/moonshotai.svg?raw';
import nvidiaMark from 'simple-icons/icons/nvidia.svg?raw';
import xiaomiMark from 'simple-icons/icons/xiaomi.svg?raw';

// Loaded lazily so the raw SVG strings stay out of the first-load shell chunk.
export const BRAND_MARK_ART: Record<string, string> = {
  alibaba: alibabaCloudMark,
  anthropic: anthropicMark,
  deepseek: deepseekMark,
  digitalocean: digitalOceanMark,
  google: googleMark,
  meta: metaMark,
  minimax: minimaxMark,
  mistral: mistralMark,
  moonshot: moonshotMark,
  nvidia: nvidiaMark,
  xiaomi: xiaomiMark,
};
