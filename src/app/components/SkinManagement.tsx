import { Check, Eye, Palette, RotateCcw } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { skinTemplates, type SkinTemplate } from "../theme/skinTemplates";
import { useSkinTheme } from "../theme/SkinThemeContext";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "./ui/FormDialog";

export function SkinManagement() {
  const { activeSkin, applySkin } = useSkinTheme();
  const [previewSkin, setPreviewSkin] = useState<SkinTemplate | null>(null);

  const applyPreview = () => {
    if (!previewSkin) return;
    applySkin(previewSkin.id);
    setPreviewSkin(null);
  };

  return <div className="min-h-full p-7" data-skin-management="true">
    <div className="mx-auto max-w-[1280px]">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-[18px] font-medium text-[#1d1d1f]"><Palette className="h-5 w-5 text-[#178a53]" />皮肤管理</div>
          <p className="mt-1 max-w-[680px] text-[12px] leading-5 text-[#8a8a8e]">统一调整所有页面、共享控件和图表的视觉风格。功能、字段、权限与点击方式保持不变。</p>
        </div>
        <div className="flex h-9 shrink-0 items-center gap-2" data-page-header-actions="true">
          <button type="button" onClick={() => applySkin("jade-workbench")} disabled={activeSkin.id === "jade-workbench"} className="inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-lg border border-[#dfe3e1] bg-white px-3 text-[11px] text-[#626965] hover:bg-[#f5f7f6] disabled:cursor-not-allowed disabled:opacity-40"><RotateCcw className="h-3.5 w-3.5" />恢复默认</button>
        </div>
      </header>

      <section className="mt-5 overflow-hidden rounded-xl border border-[#e4e8e5] bg-white" aria-label="页面皮肤模板列表">
        <div className="flex items-center justify-between gap-3 border-b border-[#edf0ee] px-4 py-3">
          <div><div className="text-[13px] font-medium text-[#303734]">预设模板</div><div className="mt-0.5 text-[10px] text-[#8a9690]">当前：{activeSkin.name}</div></div>
          <span className="text-[10px] tabular-nums text-[#98a19c]">{skinTemplates.length} 套</span>
        </div>
        <div className="grid gap-px bg-[#edf0ee] md:grid-cols-2">
          {skinTemplates.map((template) => {
            const selected = template.id === activeSkin.id;
            return <button key={template.id} type="button" onClick={() => setPreviewSkin(template)} className="group flex min-h-[126px] min-w-0 items-center gap-4 bg-white px-4 py-3 text-left transition-colors hover:bg-[#fafcfb]" aria-pressed={selected} data-skin-template={template.id}>
              <SkinPreview template={template} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2"><span className="truncate text-[13px] font-medium text-[#303734]">{template.name}</span>{selected ? <span className="inline-flex shrink-0 items-center gap-1 text-[10px] text-[#178a53]"><Check className="h-3.5 w-3.5" />使用中</span> : <Eye className="h-3.5 w-3.5 shrink-0 text-[#9aa49f] opacity-0 transition-opacity group-hover:opacity-100" />}</span>
                <span className="mt-1 block text-[10px] leading-5 text-[#747f79]">{template.description}</span>
                <span className="mt-2 block text-[9px] text-[#a0a8a3]">{template.sourceLabel} · {template.mode === "dark" ? "深色" : "浅色"}</span>
              </span>
            </button>;
          })}
        </div>
      </section>

      <div className="mt-3 rounded-lg border px-4 py-3 text-[10px] leading-5" style={{ background: "var(--sda-surface-subtle)", borderColor: "var(--sda-border)", color: "var(--sda-text-secondary)" }}>皮肤选择按当前浏览器、账号和机构保存。图表内单独选择的样式模板仍可覆盖当前图表，下一次更换全局皮肤时会重新使用该皮肤的图表默认样式。</div>
    </div>

    {previewSkin ? <FormDialog title={previewSkin.name} description="皮肤预览会覆盖页面底色、字体、控件、弹窗、表格与图表表现，不改变任何操作。" onClose={() => setPreviewSkin(null)} widthClassName="max-w-[920px]" heightClassName="max-h-[min(82vh,760px)]" ariaLabel="皮肤样式预览" dataAttributes={{ "data-skin-preview-dialog": previewSkin.id }} footer={<><FormDialogCancelButton onClick={() => setPreviewSkin(null)}>关闭</FormDialogCancelButton><FormDialogPrimaryButton onClick={applyPreview} disabled={previewSkin.id === activeSkin.id}>{previewSkin.id === activeSkin.id ? "当前正在使用" : "更换皮肤"}</FormDialogPrimaryButton></>}>
      <SkinPreview template={previewSkin} expanded />
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <SkinTokenSummary label="强调色" value={previewSkin.tokens.brand} color={previewSkin.tokens.brand} />
        <SkinTokenSummary label="页面底色" value={previewSkin.tokens.canvas} color={previewSkin.tokens.canvas} />
        <SkinTokenSummary label="默认图表" value={previewSkin.chartTemplateId.replace("chart-", "")} color={previewSkin.tokens.brandStrong} />
      </div>
    </FormDialog> : null}
  </div>;
}

function SkinPreview({ template, expanded = false }: { template: SkinTemplate; expanded?: boolean }) {
  const { tokens } = template;
  const style = {
    "--preview-canvas": tokens.canvas,
    "--preview-surface": tokens.surface,
    "--preview-subtle": tokens.surfaceSubtle,
    "--preview-sidebar": tokens.sidebar,
    "--preview-text": tokens.text,
    "--preview-secondary": tokens.textSecondary,
    "--preview-border": tokens.borderControl,
    "--preview-brand": tokens.brand,
    "--preview-brand-soft": tokens.brandSoft,
    "--preview-radius": tokens.radius,
    fontFamily: tokens.fontFamily,
  } as CSSProperties;
  if (!expanded) return <span className="grid h-[86px] w-[136px] shrink-0 grid-cols-[34px_1fr] overflow-hidden rounded-lg border shadow-sm" style={{ ...style, background: "var(--preview-canvas)", borderColor: "var(--preview-border)", boxShadow: `0 8px 20px ${tokens.shadow}` }} data-skin-live-preview={template.id}>
    <span className="border-r p-1.5" style={{ background: "var(--preview-sidebar)", borderColor: "var(--preview-border)" }}><i className="block h-3 w-3 rounded-[3px]" style={{ background: "var(--preview-brand)" }} /><i className="mt-3 block h-1 rounded-full" style={{ background: "var(--preview-brand-soft)" }} /><i className="mt-2 block h-1 rounded-full opacity-60" style={{ background: "var(--preview-secondary)" }} /></span>
    <span className="p-2"><i className="block h-2 w-2/3 rounded-full" style={{ background: "var(--preview-text)", opacity: .78 }} /><span className="mt-2 grid grid-cols-2 gap-1"><i className="block h-4 rounded-[3px] border" style={{ background: "var(--preview-surface)", borderColor: "var(--preview-border)" }} /><i className="block h-4 rounded-[3px] border" style={{ background: "var(--preview-surface)", borderColor: "var(--preview-border)" }} /></span><span className="mt-2 flex h-7 items-end gap-1 rounded-[3px] border px-1.5 pb-1" style={{ background: "var(--preview-surface)", borderColor: "var(--preview-border)" }}>{[42, 78, 58, 88, 66].map((height, index) => <i key={index} className="block flex-1 rounded-t-[2px]" style={{ height: `${height}%`, background: index === 3 ? "var(--preview-brand)" : "var(--preview-brand-soft)" }} />)}</span></span>
  </span>;

  return <div className="grid min-h-[430px] grid-cols-[176px_1fr] overflow-hidden border" style={{ ...style, background: "var(--preview-canvas)", borderColor: "var(--preview-border)", borderRadius: "var(--preview-radius)", boxShadow: `0 18px 48px ${tokens.shadow}` }} data-skin-live-preview={template.id}>
    <aside className="border-r p-4" style={{ background: "var(--preview-sidebar)", borderColor: "var(--preview-border)" }}>
      <div className="flex items-center gap-2"><span className="flex h-7 w-7 items-center justify-center rounded-md text-white" style={{ background: "var(--preview-brand)" }}><Palette className="h-3.5 w-3.5" /></span><span className="text-[12px] font-medium" style={{ color: "var(--preview-text)" }}>Data Agent</span></div>
      <div className="mt-6 space-y-1.5">{["经营分析", "我的报表", "自助分析", "数据资产", "系统管理"].map((label, index) => <div key={label} className="rounded-md px-2.5 py-2 text-[10px]" style={{ color: index === 4 ? "var(--preview-brand)" : "var(--preview-secondary)", background: index === 4 ? "var(--preview-brand-soft)" : "transparent" }}>{label}</div>)}</div>
    </aside>
    <main className="p-5">
      <div className="flex items-start justify-between"><div><div className="text-[17px] font-medium" style={{ color: "var(--preview-text)" }}>经营分析工作台</div><div className="mt-1 text-[10px]" style={{ color: "var(--preview-secondary)" }}>页面结构与功能保持不变</div></div><button type="button" className="h-8 rounded-md px-3 text-[10px] text-white" style={{ background: "var(--preview-brand)" }}>主要操作</button></div>
      <div className="mt-5 grid grid-cols-[1.2fr_.8fr] gap-3">
        <section className="border p-3" style={{ background: "var(--preview-surface)", borderColor: "var(--preview-border)", borderRadius: "var(--preview-radius)" }}><div className="text-[11px] font-medium" style={{ color: "var(--preview-text)" }}>趋势概览</div><div className="mt-5 flex h-32 items-end gap-3 border-b" style={{ borderColor: "var(--preview-border)" }}>{[38, 62, 48, 76, 58, 90, 72].map((height, index) => <span key={index} className="flex-1 rounded-t-[3px]" style={{ height: `${height}%`, background: index === 5 ? "var(--preview-brand)" : "var(--preview-brand-soft)" }} />)}</div></section>
        <section className="border p-3" style={{ background: "var(--preview-surface)", borderColor: "var(--preview-border)", borderRadius: "var(--preview-radius)" }}><div className="text-[11px] font-medium" style={{ color: "var(--preview-text)" }}>筛选条件</div><label className="mt-4 block text-[9px]" style={{ color: "var(--preview-secondary)" }}>机构</label><div className="mt-1 h-8 border px-2 py-2 text-[9px]" style={{ color: "var(--preview-text)", borderColor: "var(--preview-border)", background: "var(--preview-subtle)", borderRadius: "calc(var(--preview-radius) - 2px)" }}>全部机构</div><label className="mt-3 block text-[9px]" style={{ color: "var(--preview-secondary)" }}>分析周期</label><div className="mt-1 h-8 border px-2 py-2 text-[9px]" style={{ color: "var(--preview-text)", borderColor: "var(--preview-border)", background: "var(--preview-subtle)", borderRadius: "calc(var(--preview-radius) - 2px)" }}>最近 30 天</div></section>
      </div>
      <section className="mt-3 overflow-hidden border" style={{ background: "var(--preview-surface)", borderColor: "var(--preview-border)", borderRadius: "var(--preview-radius)" }}><div className="grid grid-cols-4 px-3 py-2 text-[9px] font-medium" style={{ color: "var(--preview-brand)", background: "var(--preview-brand-soft)" }}><span>机构</span><span>余额</span><span>完成率</span><span>排名</span></div>{["滨江分行", "高新分行", "城南分行"].map((label, index) => <div key={label} className="grid grid-cols-4 border-t px-3 py-2 text-[9px]" style={{ color: "var(--preview-text)", borderColor: "var(--preview-border)", background: index % 2 ? "var(--preview-subtle)" : "var(--preview-surface)" }}><span>{label}</span><span>{[315.8, 208.1, 154.8][index]}</span><span>{[92, 74, 61][index]}%</span><span>{index + 1}</span></div>)}</section>
    </main>
  </div>;
}

function SkinTokenSummary({ label, value, color }: { label: string; value: string; color: string }) {
  return <div className="flex items-center gap-3 rounded-lg border px-3 py-2" style={{ background: "var(--sda-surface-subtle)", borderColor: "var(--sda-border)" }}><span className="h-7 w-7 rounded-md border border-black/5" style={{ backgroundColor: color }} /><span className="min-w-0"><span className="block text-[9px]" style={{ color: "var(--sda-text-tertiary)" }}>{label}</span><span className="block truncate text-[11px]" style={{ color: "var(--sda-text)" }}>{value}</span></span></div>;
}
