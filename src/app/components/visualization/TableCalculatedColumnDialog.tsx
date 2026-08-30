import { useMemo, useRef, useState, type DragEvent } from "react";
import { GripVertical, Plus, Trash2 } from "lucide-react";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "../ui/FormDialog";
import {
  compileVisualizationFormula,
  type VisualizationCalculatedColumnConfig,
} from "./visualizationDataModel";

const snippets = [
  { label: "+", value: " + " }, { label: "-", value: " - " }, { label: "×", value: " * " }, { label: "÷", value: " / " },
  { label: "(", value: "(" }, { label: ")", value: ")" }, { label: "SUM", value: "SUM()" }, { label: "AVERAGE", value: "AVERAGE()" },
  { label: "COUNT", value: "COUNT()" }, { label: "CASE WHEN", value: "CASE WHEN  THEN  ELSE  END" },
];

export function TableCalculatedColumnDialog({ initial, metricFields, labels, sampleValues, onCancel, onRemove, onSave }: {
  initial: VisualizationCalculatedColumnConfig;
  metricFields: string[];
  labels: Record<string, string>;
  sampleValues: Record<string, unknown>;
  onCancel: () => void;
  onRemove: () => void;
  onSave: (config: VisualizationCalculatedColumnConfig) => void;
}) {
  const [draft, setDraft] = useState(initial);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const compiled = useMemo(() => compileVisualizationFormula(draft.expression, metricFields, labels), [draft.expression, labels, metricFields]);
  const preview = useMemo(() => compiled.error ? { value: null, error: compiled.error } : compiled.evaluate(sampleValues), [compiled, sampleValues]);
  const insertAtCursor = (text: string) => {
    const editor = editorRef.current;
    const start = editor?.selectionStart ?? draft.expression.length;
    const end = editor?.selectionEnd ?? start;
    const expression = `${draft.expression.slice(0, start)}${text}${draft.expression.slice(end)}`;
    setDraft((current) => ({ ...current, expression }));
    requestAnimationFrame(() => {
      if (!editor) return;
      editor.focus();
      const cursor = start + text.length;
      editor.setSelectionRange(cursor, cursor);
    });
  };
  const dropMetric = (event: DragEvent<HTMLTextAreaElement>) => {
    event.preventDefault();
    const token = event.dataTransfer.getData("application/x-sda-metric") || event.dataTransfer.getData("text/plain");
    if (token) insertAtCursor(token);
  };
  const valid = Boolean(draft.name.trim()) && !compiled.error;
  const metricToken = (field: string) => {
    const label = String(labels[field] || field).trim() || field;
    const unique = metricFields.filter((candidate) => String(labels[candidate] || candidate).trim() === label).length === 1;
    return `[${unique ? label : field}]`;
  };
  return <FormDialog
    title="计算规则"
    description="拖入指标或输入 SQL 风格表达式。公式只在当前表格数据内计算。"
    onClose={onCancel}
    widthClassName="max-w-[860px]"
    heightClassName="max-h-[min(720px,calc(100vh-40px))]"
    zIndexClassName="z-[250]"
    bodyClassName="space-y-4"
    ariaLabel="表格计算规则"
    dataAttributes={{ "data-table-calculation-dialog": "true", "data-visual-interactive": "true" }}
    footer={<><button type="button" onClick={onRemove} className="mr-auto inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-[11px] text-[#b14f4f] hover:bg-[#fff4f3]"><Trash2 className="h-3.5 w-3.5" />删除此列</button><FormDialogCancelButton onClick={onCancel}>取消</FormDialogCancelButton><FormDialogPrimaryButton disabled={!valid} onClick={() => onSave({ ...draft, name: draft.name.trim().slice(0, 80), expression: draft.expression.trim().slice(0, 2000) })}>确定</FormDialogPrimaryButton></>}
  >
    <div className="grid gap-4 md:grid-cols-[210px_minmax(0,1fr)]">
      <aside className="rounded-xl bg-[#f6f8f7] p-3" data-calculation-metric-list="true">
        <div className="mb-1 text-[11px] font-medium text-[#34443c]">可用指标</div>
        <div className="mb-3 text-[9px] leading-4 text-[#8a9690]">拖到右侧编辑区，或单击插入</div>
        <div className="space-y-1.5">{metricFields.map((field) => <button key={field} type="button" draggable onDragStart={(event) => { const token = metricToken(field); event.dataTransfer.setData("application/x-sda-metric", token); event.dataTransfer.setData("text/plain", token); event.dataTransfer.effectAllowed = "copy"; }} onClick={() => insertAtCursor(metricToken(field))} className="flex h-9 w-full items-center gap-2 rounded-lg border border-transparent bg-white px-2.5 text-left text-[10px] text-[#53615a] shadow-sm shadow-black/[0.02] hover:border-[#b9cec1] hover:text-[#2f6f50]" data-calculation-metric={field}><GripVertical className="h-3.5 w-3.5 shrink-0 text-[#a7b1ac]" /><span className="min-w-0 flex-1 truncate">{labels[field] || field}</span><Plus className="h-3 w-3 shrink-0" /></button>)}</div>
      </aside>
      <div className="min-w-0 space-y-4">
        <label className="block"><span className="mb-1.5 block text-[10px] font-medium text-[#53615a]">列名</span><input autoFocus value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} className="h-10 w-full rounded-lg border border-[#dfe7e2] bg-white px-3 text-[12px] text-[#34443c] outline-none focus:border-[#86b49a]" maxLength={80} aria-label="计算列名称" /></label>
        <div><div className="mb-1.5 flex items-center justify-between gap-3"><span className="text-[10px] font-medium text-[#53615a]">计算规则</span><span className="text-[9px] text-[#8a9690]">支持 SUM、AVERAGE、COUNT、CASE WHEN</span></div><textarea ref={editorRef} value={draft.expression} onChange={(event) => setDraft((current) => ({ ...current, expression: event.target.value }))} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={dropMetric} className="min-h-[168px] w-full resize-y rounded-xl border border-[#dfe7e2] bg-[#fbfcfb] p-3 font-mono text-[12px] leading-6 text-[#34443c] outline-none focus:border-[#86b49a]" placeholder="示例：CASE WHEN [余额] > 0 THEN [收入] / [余额] ELSE 0 END" maxLength={2000} aria-label="计算规则表达式" data-calculation-expression="true" /></div>
        <div className="flex flex-wrap gap-1.5" data-calculation-operators="true">{snippets.map((snippet) => <button key={snippet.label} type="button" onClick={() => insertAtCursor(snippet.value)} className="h-7 rounded-md border border-[#e1e8e4] bg-white px-2.5 font-mono text-[9px] text-[#60756b] hover:border-[#b8cbc0] hover:text-[#2f6f50]">{snippet.label}</button>)}</div>
        <div className={`rounded-lg px-3 py-2.5 text-[10px] leading-5 ${preview.error ? "bg-[#fff3f1] text-[#a24d45]" : "bg-[#edf7f1] text-[#2f7655]"}`} role="status" data-calculation-validation={preview.error ? "error" : "ready"}>{preview.error ? `公式错误：${preview.error}` : `首行预览：${preview.value === null ? "空值" : new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 6 }).format(preview.value)}`}</div>
      </div>
    </div>
  </FormDialog>;
}
