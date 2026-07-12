export const VOICE_PREFERENCES_STORAGE_KEY = 'matts-v2-voice-preferences';

export type VoicePresetId = 'samantha_style' | 'mission_control' | 'technical_narrator';

export type VoicePreset = {
  id: VoicePresetId;
  label: string;
  shortLabel: string;
  sample: string;
  instruction: string;
};

export type VoicePreferences = {
  enabled: boolean;
  globalPresetId: VoicePresetId;
  language: string;
  perModelPresets: Record<string, VoicePresetId>;
  presetPickerSeen: boolean;
};

export type VoiceModelHint = {
  id?: string;
  training_nation?: string;
};

export const DEFAULT_VOICE_LANGUAGE = 'English';
export const DEFAULT_SPEECH_LANGUAGES = ['English', 'Auto', 'Chinese', 'French', 'German', 'Italian', 'Japanese', 'Korean', 'Portuguese', 'Russian', 'Spanish'];

export const VOICE_PRESETS: VoicePreset[] = [
  {
    id: 'samantha_style',
    label: 'Samantha-style Assistant',
    shortLabel: 'Samantha',
    sample: "Hello, I'm your MDE assistant.",
    instruction: 'Warm cinematic adult female assistant voice with playful curiosity, clear diction, gentle pacing, and professional boundaries. Do not impersonate any real performer.',
  },
  {
    id: 'mission_control',
    label: 'Mission Control',
    shortLabel: 'Mission',
    sample: "Hello, I'm your MDE assistant.",
    instruction: 'Calm mission-control voice, concise and operational, steady cadence, confident technical delivery.',
  },
  {
    id: 'technical_narrator',
    label: 'Technical Narrator',
    shortLabel: 'Narrator',
    sample: "Hello, I'm your MDE assistant.",
    instruction: 'Precise neutral technical narrator voice, low drama, strong clarity for code, logs, and procedural details.',
  },
];

export const DEFAULT_VOICE_PREFERENCES: VoicePreferences = {
  enabled: true,
  globalPresetId: 'mission_control',
  language: DEFAULT_VOICE_LANGUAGE,
  perModelPresets: {},
  presetPickerSeen: false,
};

export function voicePresetById(id: string | undefined): VoicePreset {
  return VOICE_PRESETS.find((preset) => preset.id === id) || VOICE_PRESETS[1];
}

function normalizePresetId(value: unknown, fallback: VoicePresetId): VoicePresetId {
  return VOICE_PRESETS.some((preset) => preset.id === value) ? value as VoicePresetId : fallback;
}

function normalizePerModelPresets(value: unknown): Record<string, VoicePresetId> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const result: Record<string, VoicePresetId> = {};
  Object.entries(value as Record<string, unknown>).forEach(([key, preset]) => {
    if (!key) return;
    result[key] = normalizePresetId(preset, DEFAULT_VOICE_PREFERENCES.globalPresetId);
  });
  return result;
}

export function loadVoicePreferences(): VoicePreferences {
  if (typeof window === 'undefined') return DEFAULT_VOICE_PREFERENCES;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(VOICE_PREFERENCES_STORAGE_KEY) || '{}');
    const row = parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {};
    return {
      enabled: typeof row.enabled === 'boolean' ? row.enabled : DEFAULT_VOICE_PREFERENCES.enabled,
      globalPresetId: normalizePresetId(row.globalPresetId, DEFAULT_VOICE_PREFERENCES.globalPresetId),
      language: typeof row.language === 'string' && row.language.trim() ? row.language : DEFAULT_VOICE_LANGUAGE,
      perModelPresets: normalizePerModelPresets(row.perModelPresets),
      presetPickerSeen: row.presetPickerSeen === true,
    };
  } catch {
    return DEFAULT_VOICE_PREFERENCES;
  }
}

export function saveVoicePreferences(preferences: VoicePreferences): VoicePreferences {
  const next: VoicePreferences = {
    enabled: preferences.enabled,
    globalPresetId: normalizePresetId(preferences.globalPresetId, DEFAULT_VOICE_PREFERENCES.globalPresetId),
    language: preferences.language || DEFAULT_VOICE_LANGUAGE,
    perModelPresets: normalizePerModelPresets(preferences.perModelPresets),
    presetPickerSeen: preferences.presetPickerSeen === true,
  };
  try {
    window.localStorage.setItem(VOICE_PREFERENCES_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Voice preferences still apply for the current render when storage is unavailable.
  }
  return next;
}

export function modelDefaultVoicePreset(model?: VoiceModelHint): VoicePresetId {
  const trainingNation = String(model?.training_nation || '').toLowerCase();
  if (trainingNation.includes('china') || trainingNation.includes('chinese')) return 'samantha_style';
  return 'mission_control';
}

export function voicePresetForModel(preferences: VoicePreferences, model?: VoiceModelHint): VoicePreset {
  const modelId = String(model?.id || '');
  if (modelId && preferences.perModelPresets[modelId]) return voicePresetById(preferences.perModelPresets[modelId]);
  return voicePresetById(modelDefaultVoicePreset(model));
}

export function voiceInstructionForPreset(preset: VoicePreset, model?: VoiceModelHint): string {
  const trainingNation = String(model?.training_nation || '').toLowerCase();
  if (trainingNation.includes('china') || trainingNation.includes('chinese')) {
    return [
      'Adult female voice speaking English with a strong Chinese accent, bright playful expression, polished technical clarity, and energetic curiosity.',
      'Use respectful bilingual cadence only; avoid caricature, ethnic stereotypes, or impersonation.',
      preset.instruction,
    ].join(' ');
  }
  return preset.instruction;
}

export function setModelVoicePreset(preferences: VoicePreferences, modelId: string, presetId: VoicePresetId): VoicePreferences {
  if (!modelId) return preferences;
  return {
    ...preferences,
    perModelPresets: {
      ...preferences.perModelPresets,
      [modelId]: normalizePresetId(presetId, preferences.globalPresetId),
    },
  };
}
