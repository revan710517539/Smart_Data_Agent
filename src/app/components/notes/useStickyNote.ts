import { useEffect, useRef, useState } from "react";
import { usePlatformContext } from "../../platform/PlatformContext";
import { fetchApplicationModule, runApplicationAction, type ApplicationModuleKey } from "../../services/applicationApi";
import {
  STICKY_NOTE_CHANGED_EVENT,
  emptyStickyNote,
  localStickyNoteKey,
  normalizeStickyNote,
  type StickyNoteRecord,
} from "./richNote";

type StickyNoteChangedDetail = {
  surface: string;
  note: StickyNoteRecord;
};

export function useStickyNote(moduleKey: ApplicationModuleKey, surface: string) {
  const { tenantId, userId } = usePlatformContext();
  const [note, setNote] = useState<StickyNoteRecord>(() => readLocalNote(surface));
  const [editing, setEditing] = useState(false);
  const saveTimer = useRef<number | null>(null);
  const skipHydrate = useRef(false);

  useEffect(() => {
    let cancelled = false;
    skipHydrate.current = false;
    fetchApplicationModule<StickyNoteModuleState>({ tenantId, userId, moduleKey })
      .then((module) => {
        if (cancelled || skipHydrate.current) return;
        setNote(hiddenOnLoad(noteFromModule(module.state, surface)));
      })
      .catch(() => {
        if (!cancelled) setNote(hiddenOnLoad(readLocalNote(surface)));
      });
    return () => { cancelled = true; };
  }, [moduleKey, surface, tenantId, userId]);

  useEffect(() => {
    const onChanged = (event: Event) => {
      const detail = (event as CustomEvent<StickyNoteChangedDetail>).detail;
      if (!detail || detail.surface !== surface) return;
      skipHydrate.current = true;
      setNote(normalizeStickyNote(detail.note));
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key !== localStickyNoteKey(surface) || !event.newValue) return;
      try {
        skipHydrate.current = true;
        setNote(normalizeStickyNote(JSON.parse(event.newValue)));
      } catch { /* ignore malformed sibling-tab payloads */ }
    };
    window.addEventListener(STICKY_NOTE_CHANGED_EVENT, onChanged);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(STICKY_NOTE_CHANGED_EVENT, onChanged);
      window.removeEventListener("storage", onStorage);
    };
  }, [surface]);

  const persist = (next: StickyNoteRecord, immediate = false) => {
    const payload = { ...next, updatedAt: new Date().toISOString() };
    skipHydrate.current = true;
    setNote(payload);
    writeLocalNote(surface, payload);
    broadcastNote(surface, payload);
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    const save = () => {
      void runApplicationAction({
        tenantId,
        userId,
        moduleKey,
        action: "set_page_sticky_note",
        payload: { surface, note: payload },
      }).catch(() => undefined);
    };
    if (immediate) save();
    else saveTimer.current = window.setTimeout(save, 700);
  };

  const show = () => {
    const next = { ...note, visible: true, items: note.items.length ? note.items : emptyStickyNote().items };
    persist(next, true);
    setEditing(true);
  };

  const hide = () => {
    persist({ ...note, visible: false }, true);
    setEditing(false);
  };

  const updateItems = (items: StickyNoteRecord["items"]) => {
    persist({ ...note, visible: true, items });
  };

  const finishEdit = () => {
    persist({ ...note, visible: true }, true);
    setEditing(false);
  };

  return {
    note,
    visible: note.visible,
    editing,
    setEditing,
    show,
    hide,
    updateItems,
    finishEdit,
    uploadContext: { tenantId, userId, reportId: `sticky-${surface}`, blockId: "sticky-note" },
  };
}

type StickyNoteModuleState = {
  pageStickyNote?: StickyNoteRecord;
  stickyNotes?: Record<string, StickyNoteRecord>;
};

function noteFromModule(state: StickyNoteModuleState, surface: string) {
  if (state.stickyNotes && state.stickyNotes[surface]) return normalizeStickyNote(state.stickyNotes[surface]);
  if (state.pageStickyNote) return normalizeStickyNote(state.pageStickyNote);
  return readLocalNote(surface);
}

function readLocalNote(surface: string): StickyNoteRecord {
  try {
    return hiddenOnLoad(normalizeStickyNote(JSON.parse(localStorage.getItem(localStickyNoteKey(surface)) || "null")));
  } catch {
    return emptyStickyNote();
  }
}

function hiddenOnLoad(note: StickyNoteRecord): StickyNoteRecord {
  return { ...note, visible: false };
}

function writeLocalNote(surface: string, note: StickyNoteRecord) {
  try {
    localStorage.setItem(localStickyNoteKey(surface), JSON.stringify(note));
  } catch { /* quota must not block editing */ }
}

function broadcastNote(surface: string, note: StickyNoteRecord) {
  window.dispatchEvent(new CustomEvent<StickyNoteChangedDetail>(STICKY_NOTE_CHANGED_EVENT, { detail: { surface, note } }));
}
