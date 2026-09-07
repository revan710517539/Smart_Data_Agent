import type { ReactNode } from "react";

export function ManagementListPage({ children, className = "", ...attributes }: { children: ReactNode; className?: string; [key: `data-${string}`]: string | undefined }) {
  return <div className={`p-7 ${className}`.trim()} data-management-list-page="true" {...attributes}>{children}</div>;
}

export function ManagementListHeader({ title, description, notice, actions }: { title: string; description: string; notice?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-7 flex items-start justify-between gap-4" data-management-list-header="true">
      <div className="min-w-0">
        <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">{title}</h2>
        <p className="mt-1 text-[13px] text-[#aeaeb2]">{description}</p>
        {notice}
      </div>
      {actions ? <div className="flex w-fit min-h-9 shrink-0 flex-wrap items-center justify-end gap-[0.2cm]" data-page-header-actions="true">{actions}</div> : null}
    </header>
  );
}

export function ManagementListSection({ children, className = "", ...attributes }: { children: ReactNode; className?: string; [key: `data-${string}`]: string | undefined }) {
  return <section className={`overflow-hidden rounded-xl border border-[#f0f0f2] bg-white ${className}`.trim()} {...attributes}>{children}</section>;
}
