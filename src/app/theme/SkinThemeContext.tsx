import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { usePlatformContext } from "../platform/PlatformContext";
import { defaultSkinTemplateId, skinTemplateById, type SkinTemplate } from "./skinTemplates";

type SkinThemeContextValue = {
  activeSkin: SkinTemplate;
  activeSkinId: string;
  applySkin: (skinId: string) => void;
};

const SkinThemeContext = createContext<SkinThemeContextValue | null>(null);
const skinChangedEvent = "sda:skin-theme-changed";

function skinStorageKey(tenantId: string, userId: string) {
  return `sda:skin-theme:v1:${tenantId || "guest"}:${userId || "guest"}`;
}

function readSkinId(key: string) {
  if (typeof window === "undefined") return defaultSkinTemplateId;
  return skinTemplateById(window.localStorage.getItem(key)).id;
}

export function SkinThemeProvider({ children }: { children: ReactNode }) {
  const { tenantId, userId } = usePlatformContext();
  const storageKey = skinStorageKey(tenantId, userId);
  const [activeSkinId, setActiveSkinId] = useState(() => readSkinId(storageKey));
  const activeSkin = useMemo(() => skinTemplateById(activeSkinId), [activeSkinId]);

  useEffect(() => {
    setActiveSkinId(readSkinId(storageKey));
  }, [storageKey]);

  useEffect(() => {
    const sync = (event: Event) => {
      if (event instanceof StorageEvent && event.key !== storageKey) return;
      const detail = (event as CustomEvent<{ key?: string; skinId?: string }>).detail;
      if (detail?.key && detail.key !== storageKey) return;
      setActiveSkinId(skinTemplateById(detail?.skinId || readSkinId(storageKey)).id);
    };
    window.addEventListener("storage", sync);
    window.addEventListener(skinChangedEvent, sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener(skinChangedEvent, sync);
    };
  }, [storageKey]);

  useLayoutEffect(() => {
    const root = document.documentElement;
    const { tokens } = activeSkin;
    root.dataset.sdaSkin = activeSkin.id;
    root.dataset.sdaSkinMode = activeSkin.mode;
    root.style.colorScheme = activeSkin.mode;
    const values: Record<string, string> = {
      "--sda-brand": tokens.brand,
      "--sda-brand-strong": tokens.brandStrong,
      "--sda-brand-soft": tokens.brandSoft,
      "--sda-brand-softer": tokens.brandSofter,
      "--sda-canvas": tokens.canvas,
      "--sda-surface": tokens.surface,
      "--sda-surface-subtle": tokens.surfaceSubtle,
      "--sda-sidebar": tokens.sidebar,
      "--sda-text": tokens.text,
      "--sda-text-secondary": tokens.textSecondary,
      "--sda-text-tertiary": tokens.textTertiary,
      "--sda-border": tokens.border,
      "--sda-border-soft": tokens.borderSoft,
      "--sda-border-control": tokens.borderControl,
      "--sda-border-strong": tokens.borderStrong,
      "--sda-shadow": tokens.shadow,
      "--sda-overlay": tokens.overlay,
      "--sda-radius-card": tokens.radius,
      "--sda-font-family": tokens.fontFamily,
    };
    Object.entries(values).forEach(([name, value]) => root.style.setProperty(name, value));
  }, [activeSkin]);

  const value = useMemo<SkinThemeContextValue>(() => ({
    activeSkin,
    activeSkinId: activeSkin.id,
    applySkin: (skinId) => {
      const next = skinTemplateById(skinId);
      window.localStorage.setItem(storageKey, next.id);
      setActiveSkinId(next.id);
      window.dispatchEvent(new CustomEvent(skinChangedEvent, { detail: { key: storageKey, skinId: next.id } }));
    },
  }), [activeSkin, storageKey]);

  return <SkinThemeContext.Provider value={value}>{children}</SkinThemeContext.Provider>;
}

export function useSkinTheme() {
  const value = useContext(SkinThemeContext);
  if (!value) throw new Error("SkinThemeProvider is missing");
  return value;
}
