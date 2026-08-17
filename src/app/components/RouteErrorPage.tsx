import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react";
import { useRouteError } from "react-router";

export function RouteErrorPage() {
  const error = useRouteError();
  const dynamicImportFailed = isDynamicImportError(error);

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f5f5f7] px-6 py-10" data-route-error="true">
      <section className="w-full max-w-md rounded-2xl border border-[#e5e5ea] bg-white p-6 shadow-[0_12px_36px_rgba(0,0,0,0.06)]">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#fff4e5] text-[#b26a00]">
          <AlertTriangle className="h-5 w-5" />
        </div>
        <h1 className="mt-4 text-[18px] font-semibold tracking-tight text-[#1d1d1f]">
          {dynamicImportFailed ? "页面资源需要重新加载" : "页面暂时无法打开"}
        </h1>
        <p className="mt-2 text-[13px] leading-6 text-[#636366]">
          {dynamicImportFailed
            ? "开发服务更新或短暂中断后，浏览器中的旧页面资源已失效。重新加载即可获取最新页面，不会影响已保存的数据。"
            : "页面运行时遇到异常。你可以重新加载页面；若问题持续出现，请确认本地前端服务仍在运行。"}
        </p>
        <div className="mt-5 flex items-center gap-2">
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3.5 text-[12px] text-white transition-colors hover:bg-[#2c2c2e]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            重新加载页面
          </button>
          <button
            type="button"
            onClick={() => window.location.assign("/self-analysis/query")}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#d1d1d6] bg-white px-3.5 text-[12px] text-[#3a3a3c] transition-colors hover:bg-[#f5f5f7]"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            返回智能分析
          </button>
        </div>
      </section>
    </main>
  );
}

function isDynamicImportError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || "");
  return /dynamically imported module|importing a module script failed|error loading dynamically imported module/i.test(message);
}
