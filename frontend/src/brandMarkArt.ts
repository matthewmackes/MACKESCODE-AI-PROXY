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

function tileMark(label: string, shape: 'ring' | 'grid' | 'stack' | 'slash' | 'spark' = 'ring'): string {
  const escaped = label.replace(/[<>&"]/g, '');
  const shapes: Record<string, string> = {
    ring: '<circle cx="12" cy="12" r="8.2" style="fill:none;stroke:currentColor" stroke-width="2.4"/><circle cx="12" cy="12" r="2.7" fill="currentColor"/>',
    grid: '<rect x="4" y="4" width="7" height="7" rx="1.2" fill="currentColor"/><rect x="13" y="4" width="7" height="7" rx="1.2" fill="currentColor"/><rect x="4" y="13" width="7" height="7" rx="1.2" fill="currentColor"/><rect x="13" y="13" width="7" height="7" rx="1.2" fill="currentColor"/>',
    stack: '<path d="M5 7h14v3H5zM5 11h14v3H5zM5 15h14v3H5z" fill="currentColor"/>',
    slash: '<path d="M6 18 18 6M7 7h10v10H7z" style="fill:none;stroke:currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
    spark: '<path d="M12 3 9.8 9.8 3 12l6.8 2.2L12 21l2.2-6.8L21 12l-6.8-2.2z" fill="currentColor"/>',
  };
  return `<svg viewBox="0 0 24 24" role="img" xmlns="http://www.w3.org/2000/svg">${shapes[shape]}<text x="12" y="22" text-anchor="middle" font-size="5" font-family="IBM Plex Sans, Arial, sans-serif" font-weight="700" fill="currentColor">${escaped}</text></svg>`;
}

const arceeMark = tileMark('AR', 'slash');
const baaiMark = tileMark('BA', 'stack');
const blackForestMark = tileMark('BF', 'spark');
const microsoftMark = tileMark('MS', 'grid');
const openAiMark = tileMark('AI', 'ring');
const stabilityMark = tileMark('SD', 'spark');
const zhipuMark = tileMark('GL', 'stack');

// Loaded lazily so the raw SVG strings stay out of the first-load shell chunk.
export const BRAND_MARK_ART: Record<string, string> = {
  alibaba: alibabaCloudMark,
  anthropic: anthropicMark,
  arcee: arceeMark,
  baai: baaiMark,
  blackforest: blackForestMark,
  deepseek: deepseekMark,
  digitalocean: digitalOceanMark,
  google: googleMark,
  meta: metaMark,
  microsoft: microsoftMark,
  minimax: minimaxMark,
  mistral: mistralMark,
  moonshot: moonshotMark,
  nvidia: nvidiaMark,
  openai: openAiMark,
  stability: stabilityMark,
  xiaomi: xiaomiMark,
  zhipu: zhipuMark,
};
