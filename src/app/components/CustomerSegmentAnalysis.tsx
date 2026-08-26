import { useEffect, useRef, useState } from "react";
import { CheckCircle2, FileSpreadsheet, Upload, X } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { fetchApplicationModule } from "../services/applicationApi";
import {
  confirmCustomerSegmentList,
  previewCustomerSegmentList,
  type CustomerSegmentListMetadata,
  type CustomerSegmentListPreview,
} from "../services/customerSegmentApi";
import {
  PAGE_DATA_PAGE_GUTTER_CLASS,
  PageDataVisualizationModules,
  usePageDataComposer,
} from "./page-data/PageDataComposer";
import { StandardAnalysisPageHeader, StandardAnalysisPageStickyNote } from "./page-data/StandardAnalysisPage";
import { useStickyNote } from "./notes/useStickyNote";

type CustomerSegmentState = { customerSegmentList?: CustomerSegmentListMetadata | null };

export function CustomerSegmentAnalysis() {
  const { tenantId, userId, isSuperAdmin } = usePlatformContext();
  const [customerList, setCustomerList] = useState<CustomerSegmentListMetadata | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [workspaceRevision, setWorkspaceRevision] = useState(0);
  const pageData = usePageDataComposer({
    pageCode: "customer_segment_analysis",
    moduleKey: "customer_segment_analysis",
    railPageKey: "customer-segment-analysis",
    refreshKey: workspaceRevision,
  });
  const stickyNote = useStickyNote("customer_segment_analysis", "customer_segment_analysis");

  useEffect(() => {
    if (!isSuperAdmin) pageData.setMode("browse");
  }, [isSuperAdmin, pageData.setMode]);

  useEffect(() => {
    let cancelled = false;
    setLoadingList(true);
    setListError("");
    fetchApplicationModule<CustomerSegmentState>({ tenantId, userId, moduleKey: "customer_segment_analysis" })
      .then((response) => {
        if (!cancelled) setCustomerList(response.state.customerSegmentList || null);
      })
      .catch((error) => {
        if (!cancelled) setListError(apiErrorMessage(error, "客群名单状态读取失败。"));
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false);
      });
    return () => { cancelled = true; };
  }, [tenantId, userId]);

  return <div className={PAGE_DATA_PAGE_GUTTER_CLASS} data-customer-segment-analysis="true">
    <StandardAnalysisPageHeader
      title="分客群分析"
      description="以上传客户号名单为分析主表，统一筛选页面全部明细数据和可视化图表"
      stickyNote={stickyNote}
      editController={pageData}
      canEditLayout={isSuperAdmin}
      headerDataAttribute="customer-segment-analysis"
      leadingActions={<>
        {customerList && <span className="inline-flex h-9 items-center rounded-lg border border-[#dce9e0] bg-[#f6faf7] px-3 text-[12px] text-[#5e7165]" data-customer-segment-current-list="true">当前名单 · {customerList.customerCount.toLocaleString("zh-CN")} 个客户号</span>}
        <button type="button" onClick={() => setUploadOpen(true)} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#178a53] px-3 text-[12px] text-white hover:bg-[#127647]" data-upload-customer-segment-list="true"><Upload className="h-3.5 w-3.5" />上传客群名单</button>
      </>}
    />
    <StandardAnalysisPageStickyNote stickyNote={stickyNote} />
    {loadingList ? <CustomerSegmentStateCard message="正在读取当前客群名单…" /> : listError ? <CustomerSegmentStateCard message={listError} error /> : !customerList ? <CustomerSegmentStateCard message="请先上传 Excel 客户号名单。系统校验并确认后，页面中的所有图表才会按该名单统计。" /> : <CustomerSegmentWorkspace pageData={pageData} canEdit={isSuperAdmin} />}
    {uploadOpen && <CustomerSegmentUploadModal
      tenantId={tenantId}
      userId={userId}
      onClose={() => setUploadOpen(false)}
      onConfirmed={(metadata) => {
        setCustomerList(metadata);
        setUploadOpen(false);
        setWorkspaceRevision((value) => value + 1);
      }}
    />}
  </div>;
}

function CustomerSegmentWorkspace({ pageData, canEdit }: { pageData: ReturnType<typeof usePageDataComposer>; canEdit: boolean }) {
  if (pageData.loading && !pageData.assets.length) return <CustomerSegmentStateCard message="正在读取分客群页面数据…" />;
  return <section data-customer-segment-workspace="true">
    {(pageData.hasSelectedPageData || pageData.mode === "edit")
      ? <PageDataVisualizationModules controller={pageData} showEditorControls={canEdit} layoutEditable={canEdit} showAssetPicker />
      : null}
    {pageData.waitingForPageDataRows && !pageData.hasSelectedPageData ? <CustomerSegmentStateCard message="正在读取分客群页面数据…" /> : null}
    {!pageData.loading && !pageData.waitingForPageDataRows && !pageData.hasSelectedPageData ? <CustomerSegmentStateCard message={pageData.notice || "暂无分客群明细数据。请由超级管理员在站内数据的“分客群页面”中新增。"} /> : null}
  </section>;
}

function CustomerSegmentUploadModal({ tenantId, userId, onClose, onConfirmed }: { tenantId: string; userId: string; onClose: () => void; onConfirmed: (metadata: CustomerSegmentListMetadata) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CustomerSegmentListPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !checking && !confirming) onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [checking, confirming, onClose]);

  const selectFile = async (nextFile: File | null) => {
    setFile(nextFile);
    setPreview(null);
    setError("");
    if (!nextFile) return;
    if (!nextFile.name.toLowerCase().endsWith(".xlsx")) {
      setError("仅支持 .xlsx 格式的 Excel 客户号名单。");
      return;
    }
    setChecking(true);
    try {
      const response = await previewCustomerSegmentList({ tenantId, userId, file: nextFile });
      setPreview(response.preview);
    } catch (reason) {
      setError(apiErrorMessage(reason, "客户号名单校验失败。"));
    } finally {
      setChecking(false);
    }
  };

  const confirm = async () => {
    if (!file || !preview) return;
    setConfirming(true);
    setError("");
    try {
      const response = await confirmCustomerSegmentList({ tenantId, userId, file, expectedContentHash: preview.content_hash });
      onConfirmed(response.customer_list);
    } catch (reason) {
      setError(apiErrorMessage(reason, "客群名单保存失败。"));
    } finally {
      setConfirming(false);
    }
  };

  return <div className="fixed inset-0 z-[170] flex items-center justify-center bg-[rgba(18,33,27,0.28)] p-4" onMouseDown={(event) => { if (event.target === event.currentTarget && !checking && !confirming) onClose(); }} data-customer-segment-upload-overlay="true">
    <section role="dialog" aria-modal="true" aria-labelledby="customer-segment-upload-title" className="flex max-h-[86vh] w-full max-w-[560px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/15" onMouseDown={(event) => event.stopPropagation()}>
      <div className="flex items-start justify-between border-b border-[#f0f0f2] px-5 py-4"><div><h3 id="customer-segment-upload-title" className="text-[15px] text-[#1d1d1f]">上传客群名单</h3><p className="mt-1 text-[11px] leading-5 text-[#8a8a8e]">仅读取首个工作表 A 列；不识别表头，A1 即第一个客户号，其他列不读取。</p></div><button type="button" aria-label="关闭客群名单弹窗" disabled={checking || confirming} onClick={onClose} className="rounded-lg p-2 text-[#8a8a8e] hover:bg-[#f2f2f7] disabled:opacity-50"><X className="h-4 w-4" /></button></div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        <input ref={inputRef} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="hidden" onChange={(event) => void selectFile(event.target.files?.[0] || null)} />
        <button type="button" disabled={checking || confirming} onClick={() => inputRef.current?.click()} className="flex min-h-[112px] w-full items-center justify-center gap-3 rounded-xl border border-dashed border-[#bfd7c8] bg-[#f8fbf9] px-5 text-left hover:bg-[#f3f8f5] disabled:opacity-50" data-customer-segment-file-picker="true"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-[#178a53] shadow-sm"><FileSpreadsheet className="h-5 w-5" /></span><span><span className="block text-[13px] text-[#31473a]">{file?.name || "选择 Excel 客户号名单"}</span><span className="mt-1 block text-[10px] text-[#8a978f]">无表头 · 只读取 A 列 · 最多 20,000 个去重客户号</span></span></button>
        {checking && <div className="rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-4 py-3 text-[11px] text-[#7a7a80]">正在校验格式并过滤重复客户号…</div>}
        {preview && <div className="rounded-xl border border-[#cfe7d8] bg-[#f4faf6] p-4" data-customer-segment-preview="true"><div className="flex items-center gap-2 text-[12px] text-[#177a4d]"><CheckCircle2 className="h-4 w-4" />校验通过</div><div className="mt-3 text-[30px] font-medium tracking-tight text-[#1d1d1f]">{preview.customer_count.toLocaleString("zh-CN")}</div><div className="text-[11px] text-[#6d7c73]">个不重复客户号</div><div className="mt-3 flex flex-wrap gap-2 text-[10px] text-[#78867e]"><span className="rounded-md bg-white px-2 py-1">已过滤重复 {preview.duplicate_count} 个</span>{preview.blank_count > 0 && <span className="rounded-md bg-white px-2 py-1">已忽略空行 {preview.blank_count} 行</span>}{preview.other_columns_ignored && <span className="rounded-md bg-white px-2 py-1">其他列未读取</span>}</div></div>}
        {error && <div className="rounded-lg border border-[#ffd7d7] bg-[#fff5f5] px-3 py-2 text-[11px] leading-5 text-[#c62828]">{error}</div>}
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-[#f0f0f2] px-5 py-4"><button type="button" disabled={checking || confirming} onClick={onClose} className="h-9 rounded-lg border border-[#e5e5ea] px-4 text-[12px] text-[#636366] hover:bg-[#f7f7f8] disabled:opacity-50">取消</button><button type="button" disabled={!preview || checking || confirming} onClick={() => void confirm()} className="h-9 rounded-lg bg-[#178a53] px-5 text-[12px] text-white hover:bg-[#127647] disabled:opacity-40" data-customer-segment-confirm="true">{confirming ? "保存中…" : "确认"}</button></div>
    </section>
  </div>;
}

function CustomerSegmentStateCard({ message, error = false }: { message: string; error?: boolean }) {
  return <div className={`rounded-xl border px-6 py-16 text-center text-[12px] ${error ? "border-[#ffd7d7] bg-[#fff8f8] text-[#c62828]" : "border-[#f0f0f2] bg-white text-[#9a9aa0]"}`} data-customer-segment-state={error ? "error" : "empty"}>{message}</div>;
}
