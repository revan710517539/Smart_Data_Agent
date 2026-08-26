import { useEffect, useState, type MouseEvent as ReactMouseEvent } from "react";
import { createPortal } from "react-dom";
import { Trash2 } from "lucide-react";

export type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description?: string;
  hint?: string;
  error?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  busyLabel?: string;
  busy?: boolean;
  disabledConfirm?: boolean;
  zIndexClass?: string;
  overlayAttrs?: Record<string, string>;
  dialogAttrs?: Record<string, string>;
  titleId?: string;
  descriptionId?: string;
  onCancel: () => void;
  onConfirm: () => void;
};

function dataAttrBag(source: Record<string, unknown> | undefined) {
  const bag: Record<string, string> = {};
  if (!source) return bag;
  Object.entries(source).forEach(([key, value]) => {
    if (typeof value === "string" && key.startsWith("data-")) bag[key] = value;
  });
  return bag;
}

export function ConfirmDialog({
  open,
  title,
  description,
  hint,
  error,
  confirmLabel = "确认删除",
  cancelLabel = "取消",
  busyLabel = "删除中...",
  busy = false,
  disabledConfirm = false,
  zIndexClass = "z-[200]",
  overlayAttrs,
  dialogAttrs,
  titleId = "app-confirm-title",
  descriptionId = "app-confirm-desc",
  onCancel,
  onConfirm,
  ...rest
}: ConfirmDialogProps & Record<string, unknown>) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [busy, onCancel, open]);

  if (!open || typeof document === "undefined") return null;

  const closeOverlay = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget && !busy) onCancel();
  };
  const overlayData = dataAttrBag(overlayAttrs);
  const dialogData = dataAttrBag(dialogAttrs);
  Object.entries(rest).forEach(([key, value]) => {
    if (typeof value !== "string" || !key.startsWith("data-")) return;
    if (key.includes("dialog") && !key.includes("overlay")) dialogData[key] = value;
    else overlayData[key] = value;
  });

  return createPortal(
    <div
      className={`fixed inset-0 ${zIndexClass} flex items-center justify-center bg-black/20 px-4`}
      role="presentation"
      data-app-confirm-overlay="true"
      onMouseDown={closeOverlay}
      {...overlayData}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        data-app-confirm-dialog="true"
        className="w-full max-w-[420px] rounded-xl border border-[#e5e5ea] bg-white p-5 shadow-2xl shadow-black/20"
        onMouseDown={(event) => event.stopPropagation()}
        {...dialogData}
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#fff0f0] text-[#d93025]">
            <Trash2 className="h-4 w-4" />
          </div>
          <div>
            <h3 id={titleId} className="text-[14px] text-[#1d1d1f]">{title}</h3>
            {description ? <p id={descriptionId} className="mt-1.5 text-[12px] leading-[1.7] text-[#636366]">{description}</p> : null}
            {hint ? <p className="mt-1 text-[11px] leading-[1.6] text-[#aeaeb2]">{hint}</p> : null}
          </div>
        </div>
        {error ? <p className="mt-3 text-[11px] leading-[1.6] text-[#d93025]" role="alert">{error}</p> : null}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={busy} className="h-9 rounded-lg border border-[#e5e5ea] bg-white px-4 text-[12px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-50">{cancelLabel}</button>
          <button type="button" onClick={onConfirm} disabled={busy || disabledConfirm} className="h-9 rounded-lg bg-[#d93025] px-4 text-[12px] text-white hover:bg-[#c5221f] disabled:cursor-not-allowed disabled:opacity-40">{busy ? busyLabel : confirmLabel}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

type ConfirmRequest = Omit<ConfirmDialogProps, "open" | "onCancel" | "onConfirm" | "busy">;

type HostState = ConfirmRequest & { open: boolean; resolve?: (value: boolean) => void };

const listeners = new Set<() => void>();
let hostState: HostState = { open: false, title: "" };

function emitConfirmHost() {
  listeners.forEach((listener) => listener());
}

export function askConfirm(request: ConfirmRequest): Promise<boolean> {
  return new Promise((resolve) => {
    hostState.resolve?.(false);
    hostState = { ...request, open: true, resolve };
    emitConfirmHost();
  });
}

export function ConfirmDialogHost() {
  const [state, setState] = useState<HostState>(hostState);
  useEffect(() => {
    const sync = () => setState({ ...hostState });
    listeners.add(sync);
    return () => { listeners.delete(sync); };
  }, []);
  const finish = (value: boolean) => {
    state.resolve?.(value);
    hostState = { open: false, title: "", resolve: undefined };
    emitConfirmHost();
  };
  const { resolve: _resolve, open, ...request } = state;
  return (
    <ConfirmDialog
      {...request}
      open={open}
      onCancel={() => finish(false)}
      onConfirm={() => finish(true)}
    />
  );
}
