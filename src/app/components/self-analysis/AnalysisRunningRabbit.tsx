export function AnalysisRunningRabbit() {
  return (
    <div className="analysis-rabbit-track" role="img" aria-label="分析运行中，小兔子正在慢慢奔跑">
      <span className="analysis-rabbit-runner">
        <svg viewBox="0 0 36 22" className="h-[18px] w-7" aria-hidden="true">
          <circle cx="8.2" cy="13.4" r="3.1" fill="#fff" stroke="#777181" strokeWidth="1.15" />
          <ellipse cx="18.1" cy="14.1" rx="8.2" ry="5.8" fill="#fff" stroke="#777181" strokeWidth="1.15" />
          <path d="M22.7 8.9c-.4-5.3.6-7.5 2.1-7.4 1.5.1 1.8 3.1 1.3 7.8" fill="#fff" stroke="#777181" strokeWidth="1.15" strokeLinecap="round" />
          <path d="M27 9.1c1.1-4.8 2.6-6.8 4-6.3 1.4.5.8 3.7-1.2 7.6" fill="#fff" stroke="#777181" strokeWidth="1.15" strokeLinecap="round" />
          <path d="M24.5 3.4c.1 1.4.1 2.9-.1 4.3M29.8 4.5c-.3 1.3-.8 2.7-1.4 4" fill="none" stroke="#f2aebd" strokeWidth="1.05" strokeLinecap="round" />
          <circle cx="27.6" cy="13" r="5" fill="#fff" stroke="#777181" strokeWidth="1.15" />
          <circle cx="29.2" cy="11.9" r=".72" fill="#39343f" />
          <circle cx="25.2" cy="14.2" r="1.15" fill="#f7c6d0" opacity=".82" />
          <path d="M32 13.6c.9.1 1.5.4 2 .9-.6.4-1.3.6-2 .6" fill="#f7c6d0" stroke="#777181" strokeWidth=".75" strokeLinejoin="round" />
          <path d="M18 13.5c1.7-1.2 3.4-1.2 5 0" fill="none" stroke="#c7b2d9" strokeWidth="1.25" strokeLinecap="round" />
          <path className="analysis-rabbit-leg" d="M15.3 18.1l-3.1 2m10.1-1.7 3.1 1.4" fill="none" stroke="#777181" strokeWidth="1.35" strokeLinecap="round" />
        </svg>
      </span>
    </div>
  );
}
