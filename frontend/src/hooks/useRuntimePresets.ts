import { useEffect, useState } from 'react';

import {
  loadRuntimePresets,
  type RuntimePresetMetadata,
} from '@/config/presetMetadata';

export const useRuntimePresets = () => {
  const [presets, setPresets] = useState<RuntimePresetMetadata[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadRuntimePresets()
      .then((loaded) => {
        if (!cancelled) {
          setPresets(loaded);
          setReady(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { presets, ready };
};