import { forwardRef, type ComponentPropsWithoutRef } from "react";
import { cn } from "./utils";

export type AppSelectProps = ComponentPropsWithoutRef<"select"> & {
  controlSize?: "compact" | "default";
};

// Native selection semantics are retained for dense workbench forms while the
// visual, focus, disabled and sizing contract stays uniform across SDA.
export const AppSelect = forwardRef<HTMLSelectElement, AppSelectProps>(function AppSelect(
  { className, controlSize = "default", ...props },
  ref,
) {
  return (
    <select
      ref={ref}
      data-app-select="true"
      data-control-size={controlSize}
      className={cn(
        className,
        "min-w-0 rounded-lg border border-[#dfe3e1] bg-white px-3 text-[12px] text-[#303532] outline-none transition-[border-color,box-shadow,background-color] hover:border-[#c6cfca] focus:border-[#75ad8d] focus:ring-2 focus:ring-[#178a53]/10 disabled:cursor-not-allowed disabled:bg-[#f7f8f7] disabled:text-[#a1a7a3]",
        controlSize === "compact" ? "h-8" : "h-10",
      )}
      {...props}
    />
  );
});
