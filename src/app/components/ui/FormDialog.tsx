import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { type ReactNode } from "react";
import { cn } from "./utils";

export type FormDialogProps = {
  open?: boolean;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  busy?: boolean;
  closeOnOutside?: boolean;
  widthClassName?: string;
  heightClassName?: string;
  bodyClassName?: string;
  contentClassName?: string;
  overlayClassName?: string;
  zIndexClassName?: string;
  ariaLabel?: string;
  dataAttributes?: Record<string, string>;
  overlayDataAttributes?: Record<string, string>;
};

export function FormDialog({
  open = true,
  title,
  description,
  children,
  footer,
  onClose,
  busy = false,
  closeOnOutside = true,
  widthClassName = "max-w-[680px]",
  heightClassName = "max-h-[min(86vh,860px)]",
  bodyClassName,
  contentClassName,
  overlayClassName,
  zIndexClassName = "z-[100]",
  ariaLabel,
  dataAttributes,
  overlayDataAttributes,
}: FormDialogProps) {
  const data = dataAttributeBag(dataAttributes);
  const overlayData = dataAttributeBag(overlayDataAttributes);
  return (
    <DialogPrimitive.Root open={open} onOpenChange={(next) => {
      if (!next && !busy) onClose();
    }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className={cn("fixed inset-0 bg-black/20", zIndexClassName, overlayClassName)}
          data-app-form-dialog-overlay="true"
          {...overlayData}
        />
        <DialogPrimitive.Content
          aria-label={ariaLabel}
          onEscapeKeyDown={(event) => { if (busy) event.preventDefault(); }}
          onInteractOutside={(event) => { if (busy || !closeOnOutside) event.preventDefault(); }}
          className={cn(
            "fixed left-1/2 top-1/2 flex w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-[#e2e6e4] bg-white shadow-2xl shadow-black/20 outline-none",
            zIndexClassName,
            widthClassName,
            heightClassName,
            contentClassName,
          )}
          data-app-form-dialog="true"
          {...data}
        >
          <div className="flex shrink-0 items-start justify-between gap-4 border-b border-[#eef1ef] px-5 py-4" data-app-form-dialog-header="true">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-[15px] font-normal leading-5 text-[#1d1d1f]">{title}</DialogPrimitive.Title>
              {description ? <DialogPrimitive.Description className="mt-1 text-[11px] leading-[1.6] text-[#8a918d]">{description}</DialogPrimitive.Description> : null}
            </div>
            <DialogPrimitive.Close asChild>
              <button type="button" disabled={busy} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[#8a8a8e] hover:bg-[#f2f2f7] disabled:opacity-40" aria-label="关闭弹窗">
                <X className="h-4 w-4" />
              </button>
            </DialogPrimitive.Close>
          </div>
          <div className={cn("min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4", bodyClassName)} data-app-form-dialog-body="true">
            {children}
          </div>
          {footer ? <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-[#eef1ef] bg-white px-5 py-3" data-app-form-dialog-footer="true">{footer}</div> : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function FormDialogCancelButton({ children = "取消", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" className="h-9 whitespace-nowrap rounded-lg border border-[#dfe3e1] bg-white px-4 text-[12px] text-[#626965] hover:bg-[#f5f7f6] disabled:opacity-40" {...props}>{children}</button>;
}

export function FormDialogPrimaryButton({ children, tone = "default", className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "default" | "danger" }) {
  return <button type="button" className={cn("h-9 whitespace-nowrap rounded-lg px-4 text-[12px] text-white disabled:cursor-not-allowed disabled:opacity-40", tone === "danger" ? "bg-[#d92d20] hover:bg-[#b42318]" : "bg-[#1d1d1f] hover:bg-[#2c2c2e]", className)} {...props}>{children}</button>;
}

function dataAttributeBag(source: Record<string, string> | undefined) {
  if (!source) return {};
  return Object.fromEntries(Object.entries(source).filter(([key]) => key.startsWith("data-")));
}
