import { listPresets, type StylePresetMetadata } from '@/api/endpoints';
import { GENERATE_PRESETS } from '@/config/generatePresets';
import { RESTYLE_PRESETS } from '@/config/restylePresets';
import { TRANSLATION_WITH_RESTYLE_PROMPT } from '@/config/translatePresets';

export type RuntimePresetMetadata = StylePresetMetadata & {
  prompts: {
    generate: string;
    restyle: string;
    translateRestyle: string;
  };
};

let cachedPresets: RuntimePresetMetadata[] | null = null;
let loadPromise: Promise<RuntimePresetMetadata[]> | null = null;

const fallbackDdi = (): RuntimePresetMetadata | undefined => {
  const restyle = RESTYLE_PRESETS[0];
  const generate = GENERATE_PRESETS.find((item) => item.id === 'ddi-standard');
  if (!restyle || !generate) {
    return undefined;
  }
  return {
    id: restyle.id,
    legacyIds: restyle.legacyIds,
    version: restyle.version,
    name: restyle.name,
    baseImage: 'base.png',
    sha256: restyle.sha256,
    imageUrl: restyle.imageUrl,
    prompts: {
      generate: generate.prompt,
      restyle: restyle.prompt,
      translateRestyle: TRANSLATION_WITH_RESTYLE_PROMPT,
    },
  };
};

export const loadRuntimePresets = async (): Promise<RuntimePresetMetadata[]> => {
  if (cachedPresets) {
    return cachedPresets;
  }
  if (!loadPromise) {
    loadPromise = (async () => {
      try {
        const response = await listPresets();
        const presets = response.data?.presets ?? [];
        if (presets.length > 0) {
          cachedPresets = presets as RuntimePresetMetadata[];
          return cachedPresets;
        }
      } catch {
        // fall through to local fallback
      }
      const fallback = fallbackDdi();
      cachedPresets = fallback ? [fallback] : [];
      return cachedPresets;
    })();
  }
  return loadPromise;
};

export const getRuntimePresetById = async (
  id: string
): Promise<RuntimePresetMetadata | undefined> => {
  const presets = await loadRuntimePresets();
  return presets.find(
    (preset) => preset.id === id || preset.legacyIds?.includes(id)
  );
};

export const clearRuntimePresetCache = (): void => {
  cachedPresets = null;
  loadPromise = null;
};