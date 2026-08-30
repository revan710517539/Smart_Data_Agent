"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { DayPicker } from "react-day-picker";

import { cn } from "./utils";
import { buttonVariants } from "./button";

function Calendar({
  className,
  classNames,
  showOutsideDays = true,
  ...props
}: React.ComponentProps<typeof DayPicker>) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("p-2.5 text-[#303532]", className)}
      classNames={{
        months: "flex flex-col sm:flex-row gap-2",
        month: "flex flex-col gap-3",
        caption: "flex justify-center pt-1 relative items-center w-full",
        caption_label: "text-[13px] font-medium text-[#303532]",
        nav: "flex items-center gap-1",
        nav_button: cn(
          buttonVariants({ variant: "outline" }),
          "size-7 border-[#e2e6e4] bg-white p-0 text-[#69736d] opacity-100 shadow-none hover:bg-[#f5f7f6] hover:text-[#303532]",
        ),
        nav_button_previous: "absolute left-1",
        nav_button_next: "absolute right-1",
        table: "w-full border-collapse space-x-1",
        head_row: "flex",
        head_cell:
          "w-8 rounded-md text-[11px] font-normal text-[#929994]",
        row: "flex w-full mt-2",
        cell: cn(
          "relative p-0 text-center text-sm focus-within:relative focus-within:z-20 [&:has([aria-selected])]:bg-accent [&:has([aria-selected].day-range-end)]:rounded-r-md",
          props.mode === "range"
            ? "[&:has(>.day-range-end)]:rounded-r-md [&:has(>.day-range-start)]:rounded-l-md first:[&:has([aria-selected])]:rounded-l-md last:[&:has([aria-selected])]:rounded-r-md"
            : "[&:has([aria-selected])]:rounded-md",
        ),
        day: cn(
          buttonVariants({ variant: "ghost" }),
          "size-8 rounded-lg p-0 text-[12px] font-normal text-[#404743] hover:bg-[#f0f6f2] hover:text-[#176d49] aria-selected:opacity-100",
        ),
        day_range_start:
          "day-range-start aria-selected:bg-[#178a53] aria-selected:text-white",
        day_range_end:
          "day-range-end aria-selected:bg-[#178a53] aria-selected:text-white",
        day_selected:
          "bg-[#178a53] text-white hover:bg-[#127647] hover:text-white focus:bg-[#178a53] focus:text-white",
        day_today: "bg-[#eef7f1] font-medium text-[#176d49]",
        day_outside:
          "day-outside text-[#bdc2bf] aria-selected:text-[#bdc2bf]",
        day_disabled: "text-[#c8cdca] opacity-50",
        day_range_middle:
          "aria-selected:bg-[#e8f4ec] aria-selected:text-[#176d49]",
        day_hidden: "invisible",
        ...classNames,
      }}
      components={{
        IconLeft: ({ className, ...props }) => (
          <ChevronLeft className={cn("size-4", className)} {...props} />
        ),
        IconRight: ({ className, ...props }) => (
          <ChevronRight className={cn("size-4", className)} {...props} />
        ),
      }}
      {...props}
    />
  );
}

export { Calendar };
