import { useEffect, useState } from "react";

export function AnalysisLoadingGame() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const startedAt = Date.now();
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - startedAt) / 1000)), 250);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="rounded-xl border border-[#e5e5ea] bg-[#fafbfc] px-6 py-8">
      <style>{`
        @keyframes analysis-runner { 0% { transform: translateX(0) translateY(0); } 45% { transform: translateX(170px) translateY(0); } 55% { transform: translateX(195px) translateY(-24px); } 65% { transform: translateX(220px) translateY(0); } 100% { transform: translateX(350px) translateY(0); } }
        @keyframes analysis-road { from { transform: translateX(0); } to { transform: translateX(-36px); } }
      `}</style>
      <div className="flex items-center justify-between"><div><div className="text-[13px] text-[#1d1d1f]">模型正在分析</div><div className="mt-1 text-[11px] text-[#8a8a8e]">正在完成问题理解、语义取数、证据复核和结论生成</div></div><div className="font-mono text-[20px] tabular-nums text-[#3a3a3c]">{formatSeconds(seconds)}</div></div>
      <div className="mx-auto mt-8 h-24 max-w-[520px] overflow-hidden rounded-lg border border-[#f0f0f2] bg-white">
        <div className="relative mx-auto mt-5 h-12 w-[390px] max-w-[90%] border-b border-[#8e8e93]">
          <div className="absolute bottom-0 left-1 h-8 w-5" style={{ animation: "analysis-runner 4.2s linear infinite" }}><span className="absolute left-[7px] top-0 h-2 w-2 rounded-full border border-[#1d1d1f]" /><span className="absolute left-[10px] top-2 h-3 w-px bg-[#1d1d1f]" /><span className="absolute left-[6px] top-[13px] h-px w-3 rotate-[-18deg] bg-[#1d1d1f]" /><span className="absolute left-[8px] top-5 h-px w-3 rotate-[-55deg] bg-[#1d1d1f]" /><span className="absolute left-[8px] top-5 h-px w-3 rotate-[55deg] bg-[#1d1d1f]" /></div>
          <div className="absolute bottom-0 left-[205px] h-5 w-px bg-[#8e8e93]" /><div className="absolute bottom-5 left-[199px] h-px w-3 bg-[#8e8e93]" />
          <div className="absolute bottom-[-5px] left-0 flex gap-5" style={{ animation: "analysis-road 1.2s linear infinite" }}>{Array.from({ length: 14 }, (_, index) => <span key={index} className="h-px w-4 bg-[#d1d1d6]" />)}</div>
        </div>
        <div className="mt-3 text-center text-[10px] text-[#aeaeb2]">跨过数据障碍，结果即将到达</div>
      </div>
    </div>
  );
}

function formatSeconds(seconds: number) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = (seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}
