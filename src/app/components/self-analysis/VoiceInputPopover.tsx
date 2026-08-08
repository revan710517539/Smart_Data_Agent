export function VoiceInputPopover({
  transcript,
  listening,
  error,
  onTranscriptChange,
  onAnalyze,
  onCancel,
}: {
  transcript: string;
  listening: boolean;
  error: string;
  onTranscriptChange: (value: string) => void;
  onAnalyze: () => void;
  onCancel: () => void;
}) {
  const bars = [24, 38, 56, 44, 68, 52, 34, 60, 42, 30, 48, 36];

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/10 px-4 pt-[150px]">
      <style>{`
        @keyframes voice-level {
          0%, 100% { transform: scaleY(0.45); opacity: 0.45; }
          50% { transform: scaleY(1); opacity: 1; }
        }
      `}</style>
      <div className="w-full max-w-[420px] overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/[0.12]">
        <div className="border-b border-[#f0f0f2] px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[13px] text-[#1d1d1f]">语音录入</div>
              <div className="mt-0.5 text-[11px] text-[#aeaeb2]">
                {listening ? "Fun-ASR 正在接收本机语音输入" : "可编辑识别文本后开始分析"}
              </div>
            </div>
            <span className={`h-2 w-2 rounded-full ${listening ? "bg-[#34c759]" : "bg-[#c7c7cc]"}`} />
          </div>
        </div>
        <div className="bg-[#fafbfc] px-4 py-5">
          <div className="flex h-[104px] items-center justify-center gap-1.5 rounded-lg border border-[#f0f0f2] bg-white">
            {bars.map((height, index) => (
              <span
                key={`${height}_${index}`}
                className="w-1.5 origin-center rounded-full bg-[#8e8e93]"
                style={{
                  height,
                  animationName: listening ? "voice-level" : undefined,
                  animationDuration: listening ? "980ms" : undefined,
                  animationTimingFunction: listening ? "ease-in-out" : undefined,
                  animationIterationCount: listening ? "infinite" : undefined,
                  animationDelay: listening ? `${index * 80}ms` : undefined,
                  opacity: listening ? undefined : 0.35,
                  transform: listening ? undefined : "scaleY(0.45)",
                }}
              />
            ))}
          </div>
        </div>
        <div className="px-4 pb-4">
          <textarea
            value={transcript}
            onChange={(event) => onTranscriptChange(event.target.value)}
            placeholder="语音识别文本会显示在这里，可直接修改。"
            className="min-h-[112px] w-full resize-none rounded-lg border border-[#e5e5ea] bg-white px-3 py-2 text-[13px] leading-[1.7] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
          />
          {error && <div className="mt-2 text-[11px] text-[#d93025]">{error}</div>}
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" onClick={onCancel} className="rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7]">取消</button>
            <button type="button" onClick={onAnalyze} disabled={!transcript.trim()} className="rounded-lg bg-[#1d1d1f] px-4 py-2 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-40">开始</button>
          </div>
        </div>
      </div>
    </div>
  );
}
