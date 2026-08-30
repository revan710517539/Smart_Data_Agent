import { format, isValid, parseISO } from "date-fns";
import { zhCN } from "date-fns/locale";
import { CalendarDays } from "lucide-react";
import { useState } from "react";
import { Calendar } from "./calendar";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import { cn } from "./utils";

export type DatePickerProps = {
  value: string;
  onValueChange: (value: string) => void;
  ariaLabel: string;
  placeholder?: string;
  min?: string;
  disabled?: boolean;
  autoFocus?: boolean;
  className?: string;
  onBlur?: () => void;
};

export function DatePicker({
  value,
  onValueChange,
  ariaLabel,
  placeholder = "选择日期",
  min,
  disabled = false,
  autoFocus = false,
  className,
  onBlur,
}: DatePickerProps) {
  const [open, setOpen] = useState(false);
  const selected = parseDate(value);
  const minimum = parseDate(min || "");
  return (
    <Popover open={open} onOpenChange={(next) => {
      setOpen(next);
      if (!next) onBlur?.();
    }}>
      <PopoverTrigger asChild>
        <button
          type="button"
          autoFocus={autoFocus}
          disabled={disabled}
          aria-label={ariaLabel}
          data-app-date-picker="true"
          className={cn(
            className,
            "inline-flex h-10 min-w-0 items-center justify-between gap-2 rounded-lg border border-[#dfe3e1] bg-white px-3 text-left text-[12px] text-[#303532] outline-none transition-[border-color,box-shadow,background-color] hover:border-[#c6cfca] focus-visible:border-[#75ad8d] focus-visible:ring-2 focus-visible:ring-[#178a53]/10 disabled:cursor-not-allowed disabled:bg-[#f7f8f7] disabled:text-[#a1a7a3]",
          )}
        >
          <span className={selected ? "truncate" : "truncate text-[#8f9692]"}>{selected ? format(selected, "yyyy年MM月dd日") : placeholder}</span>
          <CalendarDays className="h-3.5 w-3.5 shrink-0 text-[#748078]" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto rounded-xl border-[#dfe5e1] bg-white p-2 shadow-xl shadow-black/10" data-app-date-popover="true">
        <Calendar
          mode="single"
          locale={zhCN}
          selected={selected}
          disabled={minimum ? { before: minimum } : undefined}
          initialFocus
          onSelect={(day) => {
            if (!day) return;
            onValueChange(format(day, "yyyy-MM-dd"));
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

function parseDate(value: string) {
  if (!value) return undefined;
  const parsed = parseISO(value);
  return isValid(parsed) ? parsed : undefined;
}
