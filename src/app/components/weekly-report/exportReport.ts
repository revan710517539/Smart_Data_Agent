import type { CommentItem, TableBlock, WeeklyInstitutionReport } from "./domain";

export type WeeklyExportFormat = "html" | "pdf";

export async function prepareWeeklyExportDocument(source: HTMLElement, options: { includeComments: boolean; includeAnalysis: boolean; report: WeeklyInstitutionReport; comments: CommentItem[] }) {
  const documentNode = source.cloneNode(true) as HTMLElement;
  documentNode.classList.add("weekly-export-document");
  documentNode.querySelectorAll<HTMLInputElement>("input").forEach((input) => { const text = document.createElement("span"); text.textContent = input.value; input.replaceWith(text); });
  documentNode.querySelectorAll<HTMLTextAreaElement>("textarea").forEach((textarea) => { const text = document.createElement("p"); text.textContent = textarea.value; textarea.replaceWith(text); });
  documentNode.querySelectorAll<HTMLElement>("button, select, [contenteditable='true'], .weekly-report-print-hidden, [data-weekly-selection-action], [data-analysis-underline-layer]").forEach((element) => element.remove());
  documentNode.querySelectorAll<HTMLElement>("[data-context-rail], [data-context-rail-edge]").forEach((element) => element.remove());
  if (!options.includeAnalysis) documentNode.querySelectorAll<HTMLElement>("[data-weekly-report-ai], [data-weekly-report-ai-module]").forEach((element) => element.remove()); else documentNode.append(createWeeklyExportAnalysis(options.report));
  if (options.includeComments) documentNode.append(createWeeklyExportComments(options.comments));
  await inlineWeeklyExportImages(documentNode);
  return documentNode;
}

export function weeklyExportHtml(documentNode: HTMLElement, report: WeeklyInstitutionReport) {
  const title = `${escapeWeeklyExportHtml(report.institutionName)}经营周报`;
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><style>${weeklyExportStyles}</style></head><body><main>${documentNode.outerHTML}</main></body></html>`;
}

export async function downloadWeeklyExportPdf(documentNode: HTMLElement, filename: string) {
  const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
    import("html2canvas"),
    import("jspdf"),
  ]);
  const host = document.createElement("div");
  host.className = "weekly-export-pdf-host";
  host.style.cssText = "position:absolute;left:-100000px;top:0;width:1120px;background:#fff;padding:28px;";
  host.append(documentNode); document.body.append(host);
  try { const canvas = await html2canvas(documentNode, { backgroundColor: "#ffffff", scale: 2, useCORS: true, logging: false, windowWidth: 1120 }); const pdf = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4", compress: true }); const margin = 10; const pageWidth = 210 - margin * 2; const pageHeight = 297 - margin * 2; const renderedHeight = canvas.height * pageWidth / canvas.width; let offset = 0; let page = 0; while (offset < renderedHeight) { if (page > 0) pdf.addPage(); pdf.addImage(canvas, "PNG", margin, margin - offset, pageWidth, renderedHeight, undefined, "FAST"); offset += pageHeight; page += 1; } pdf.save(filename); } finally { host.remove(); }
}

export function downloadWeeklyExport(blob: Blob, filename: string) { const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1_000); }
export function weeklyExportFilename(report: WeeklyInstitutionReport, format: WeeklyExportFormat) { const safeInstitution = report.institutionName.replace(/[\\/:*?"<>|]/g, "_"); const safePeriod = report.period.replace(/[\\/:*?"<>|]/g, "_"); return `${safeInstitution}经营周报_${safePeriod}.${format}`; }

function createWeeklyExportAnalysis(report: WeeklyInstitutionReport) { const section = document.createElement("section"); section.className = "weekly-export-ai-section"; const blocks = report.sections.flatMap((item) => item.blocks).filter((block): block is TableBlock => block.type === "table" && Boolean(block.analysis.conclusion.trim())); const heading = document.createElement("h4"); heading.textContent = "AI 分析"; section.append(heading); if (!blocks.length) { const empty = document.createElement("p"); empty.textContent = "当前周报没有可导出的 AI 分析结论。"; section.append(empty); return section; } blocks.forEach((block) => { const item = document.createElement("article"); item.className = "weekly-export-ai-item"; const title = document.createElement("h5"); title.textContent = `${block.title} · ${block.analysis.status}`; const text = document.createElement("p"); text.textContent = block.analysis.conclusion; item.append(title, text); section.append(item); }); return section; }
function createWeeklyExportComments(comments: CommentItem[]) { const section = document.createElement("section"); section.className = "weekly-export-comments"; const heading = document.createElement("h4"); heading.textContent = "评论"; section.append(heading); if (!comments.length) { const empty = document.createElement("p"); empty.textContent = "当前周报没有待导出的公开评论。"; section.append(empty); return section; } comments.forEach((comment) => { const item = document.createElement("article"); item.className = "weekly-export-comment-item"; const meta = document.createElement("p"); meta.className = "weekly-export-comment-meta"; meta.textContent = `${comment.author} · ${comment.time || "时间未记录"} · ${comment.targetLabel}`; const text = document.createElement("p"); text.textContent = comment.text; item.append(meta, text); comment.replies.forEach((reply) => { const replyText = document.createElement("p"); replyText.className = "weekly-export-comment-reply"; replyText.textContent = `回复 · ${reply.author}：${reply.text}`; item.append(replyText); }); section.append(item); }); return section; }
async function inlineWeeklyExportImages(root: HTMLElement) { await Promise.all(Array.from(root.querySelectorAll<HTMLImageElement>("img")).map(async (image) => { if (!image.src || image.src.startsWith("data:")) return; try { const response = await fetch(image.src); if (!response.ok) return; const blob = await response.blob(); image.src = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result || "")); reader.onerror = () => reject(reader.error); reader.readAsDataURL(blob); }); } catch { /* retain optional source */ } })); }
function escapeWeeklyExportHtml(value: string) { return value.replace(/[&<>"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[character] || character)); }
const weeklyExportStyles = `* { box-sizing: border-box; } body { margin: 0; background: #f7f8fa; color: #1d1d1f; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.6; } main { max-width: 1120px; margin: 0 auto; padding: 28px; background: #fff; } h3 { margin: 0 0 12px; font-size: 24px; } h4 { margin: 28px 0 12px; padding-top: 16px; border-top: 1px solid #e5e5ea; font-size: 17px; } h5 { margin: 0 0 6px; font-size: 13px; } p { white-space: pre-wrap; } table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12px; } th, td { border: 1px solid #e5e5ea; padding: 8px; text-align: left; vertical-align: top; } th { background: #fafbfc; } img { max-width: 100%; height: auto; } .weekly-export-ai-item, .weekly-export-comment-item { margin: 10px 0; padding: 12px; border: 1px solid #e5e5ea; border-radius: 8px; background: #fafbfc; } .weekly-export-comment-meta, .weekly-export-comment-reply { color: #636366; font-size: 12px; } @media print { body { background: #fff; } main { max-width: none; padding: 0; } }`;
