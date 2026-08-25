import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { fetchMessageBoardAttachment } from "../../services/messageBoardApi";

export function MessageBoardAttachmentGallery({ attachmentIds, tenantId, userId, className = "mt-2 grid grid-cols-3 gap-2" }: { attachmentIds: string[]; tenantId: string; userId: string; className?: string }) {
  const [urls, setUrls] = useState<string[]>([]);
  const [loading, setLoading] = useState(Boolean(attachmentIds.length));
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const loaded: string[] = [];
    setLoading(Boolean(attachmentIds.length));
    setFailed(false);
    Promise.all(attachmentIds.map((id) => fetchMessageBoardAttachment(id, { tenantId, userId })))
      .then((next) => {
        loaded.push(...next);
        if (!cancelled) setUrls(next);
      })
      .catch(() => { if (!cancelled) setFailed(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => {
      cancelled = true;
      loaded.forEach(URL.revokeObjectURL);
    };
  }, [attachmentIds, tenantId, userId]);

  if (loading) return <div className="mt-2 flex h-16 items-center justify-center rounded-lg bg-[#f7f8fa] text-[#8a8a8e]"><LoaderCircle className="h-4 w-4 animate-spin" /></div>;
  if (failed) return <div className="mt-2 rounded-lg bg-[#fff7ed] px-3 py-2 text-[10px] text-[#9a5b13]">留言截图读取失败，请刷新后重试。</div>;
  return <div className={className} data-message-board-attachment-gallery="true">{urls.map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer" className="aspect-square overflow-hidden rounded-lg border border-[#ececf0] bg-[#f7f8fa]"><img src={url} alt={`留言截图 ${index + 1}`} className="h-full w-full object-cover" /></a>)}</div>;
}
