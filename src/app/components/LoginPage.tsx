import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { ClipboardList, Landmark, LogIn, Mail, UserPlus, X } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import {
  beginEnterpriseLogin,
  loginWithEmail,
  registerWithEmail,
  sendLoginSurveyBeacon,
  submitLoginSurveyDraft,
  type LoginSurveyAnswers,
  type LoginSurveyDraft,
  type LoginSurveyTrigger,
} from "../services/authApi";
import { ApiRequestError, apiErrorMessage } from "../services/apiClient";
import { createClientUuid } from "../utils/clientUuid";

export function LoginPage() {
  const navigate = useNavigate();
  const { institutions, isAuthenticated, login } = usePlatformContext();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [institution, setInstitution] = useState(institutions[0] || "");
  const [neededMetrics, setNeededMetrics] = useState("");
  const [reportUsage, setReportUsage] = useState("");
  const [notice, setNotice] = useState("");
  const [noticeKind, setNoticeKind] = useState<"error" | "success">("error");
  const [submitting, setSubmitting] = useState(false);
  const surveyMessageId = useRef("");
  const surveyDraftRef = useRef({ account: "", institution: "", neededMetrics: "", reportUsage: "" });

  useEffect(() => {
    if (isAuthenticated) navigate("/self-analysis/query", { replace: true });
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    if (!institutions.length) return;
    if (!institution || !institutions.includes(institution)) {
      setInstitution(institutions[0]);
    }
  }, [institution, institutions]);

  useEffect(() => {
    surveyDraftRef.current = { account: email, institution, neededMetrics, reportUsage };
  }, [email, institution, neededMetrics, reportUsage]);

  useEffect(() => {
    const saveBeforeLeaving = () => {
      const draft = loginSurveyDraft("pagehide", surveyDraftRef.current, surveyMessageId);
      if (draft) sendLoginSurveyBeacon(draft);
    };
    window.addEventListener("pagehide", saveBeforeLeaving);
    return () => window.removeEventListener("pagehide", saveBeforeLeaving);
  }, []);

  const authenticateAndEnter = async (survey?: LoginSurveyAnswers) => {
    const session = await loginWithEmail({ email, password, institution, survey });
    if (survey) {
      setNeededMetrics("");
      setReportUsage("");
      surveyDraftRef.current = { account: email, institution, neededMetrics: "", reportUsage: "" };
      surveyMessageId.current = "";
    }
    login(session);
    navigate("/self-analysis/query", { replace: true });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setNotice("");
    setNoticeKind("error");
    setSubmitting(true);
    try {
      if (mode === "login") {
        const survey = loginSurveyDraft("login", surveyDraftRef.current, surveyMessageId);
        await authenticateAndEnter(survey || undefined);
        return;
      }
      const contact = email.trim();
      const result = await registerWithEmail({
        name,
        email: looksLikeEmail(contact) ? contact : "",
        phone: looksLikeEmail(contact) ? "" : contact,
        password,
        institution,
      });
      setNotice(result.message || "注册申请已提交，请等待超级管理员审批。");
      setNoticeKind("success");
      setPassword("");
    } catch (error) {
      if (mode === "login" && error instanceof ApiRequestError && error.code === "external_identity_required") {
        try {
          const oidc = await beginEnterpriseLogin();
          window.location.assign(oidc.authorization_url);
          return;
        } catch (oidcError) {
          setNotice(apiErrorMessage(oidcError, "企业身份登录暂不可用"));
          return;
        }
      }
      setNotice(apiErrorMessage(error, mode === "login" ? "登录失败" : "注册失败"));
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = () => {
    setEmail("");
    setPassword("");
    setName("");
    setNeededMetrics("");
    setReportUsage("");
    setNotice("");
    setNoticeKind("error");
    setMode("login");
    surveyDraftRef.current = { account: "", institution, neededMetrics: "", reportUsage: "" };
    surveyMessageId.current = "";
  };

  const cancelAndSaveSurvey = () => {
    const draft = loginSurveyDraft("cancel", surveyDraftRef.current, surveyMessageId);
    if (draft) void submitLoginSurveyDraft(draft).catch(() => undefined);
    cancel();
  };

  const contactReady = Boolean(email.trim());
  const registerReady = contactReady && Boolean(institution);
  const loginReady = contactReady && Boolean(password);
  const busy = submitting;

  return (
    <div className="flex min-h-screen items-start justify-center bg-[#f6f8f7] px-4 py-6 sm:px-6 lg:items-center">
      <main className="grid w-full max-w-[900px] overflow-hidden rounded-[20px] border border-[#e2e8e5] bg-white shadow-[0_22px_60px_rgba(22,48,37,0.09)] lg:grid-cols-2">
        <aside
          className="relative border-b border-[#e3ece7] bg-[#f3f8f5] px-6 py-6 sm:px-7 lg:border-b-0 lg:border-r"
          data-login-survey="true"
        >
          <div>
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#0f8554] shadow-sm shadow-[#0f8554]/20">
                <ClipboardList className="h-[18px] w-[18px] text-white" />
              </div>
              <div>
                <div className="text-[11px] font-medium tracking-[0.14em] text-[#0f8554]">DATA VOICE</div>
                <h2 className="mt-1 text-[18px] font-medium tracking-tight text-[#17362a]">数据使用小调查</h2>
                <p className="mt-1.5 max-w-[320px] text-[12px] leading-5 text-[#6f7f77]">
                  两个回答会合并为一条留言，帮助我们持续优化指标与报表体验。
                </p>
              </div>
            </div>

            <div className="mt-5 space-y-3.5">
              <SurveyQuestion
                index="01"
                label="你需要什么指标？"
                value={neededMetrics}
                onChange={(value) => {
                  surveyDraftRef.current.neededMetrics = value;
                  setNeededMetrics(value);
                }}
                placeholder="例如：客户转化率、产品收益率、逾期迁徙率……"
                disabled={mode !== "login" || busy}
              />
              <SurveyQuestion
                index="02"
                label="你平时怎么用报表？"
                value={reportUsage}
                onChange={(value) => {
                  surveyDraftRef.current.reportUsage = value;
                  setReportUsage(value);
                }}
                placeholder="例如：晨会复盘、经营跟踪、客户分析、管理汇报……"
                disabled={mode !== "login" || busy}
              />
            </div>

          </div>
        </aside>

        <section className="bg-white">
          <div className="border-b border-[#f0f0f2] px-6 py-6 sm:px-7">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#0f8554]">
                <Landmark className="h-[18px] w-[18px] text-white" />
              </div>
              <div>
                <h1 className="text-[19px] font-medium tracking-tight text-[#1d1d1f]">Data Agent</h1>
                <p className="mt-0.5 text-[12px] text-[#8a8a8e]">
                  {mode === "login"
                    ? "账号登录后进入机构工作台"
                    : "注册后默认申请所选机构操作员，需超级管理员同意"}
                </p>
              </div>
            </div>
          </div>

          <form onSubmit={submit} className="space-y-3.5 px-6 py-5 sm:px-7">
            {mode === "register" && (
              <LoginInput label="姓名" value={name} onChange={setName} placeholder="选填，默认用账号生成" />
            )}
            <LoginInput
              label={mode === "register" ? "手机号或邮箱" : "账号"}
              value={email}
              onChange={(value) => {
                surveyDraftRef.current.account = value;
                setEmail(value);
              }}
              placeholder={mode === "register" ? "请输入手机号或邮箱" : "name@bank.com 或手机号"}
            />
            <div>
              <LoginInput
                label="密码"
                value={password}
                onChange={setPassword}
                placeholder="请输入密码"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
              />
              <p className="mt-1.5 text-[11px] leading-5 text-[#8e8e93]">
                {mode === "login"
                  ? "请输入您的账号密码。新账号请使用初始密码，登录后可在左侧栏修改。"
                  : "可不填。未填写时使用初始密码，审批通过后登录并尽快修改。"}
              </p>
            </div>
            <label>
              <span className="mb-1.5 block text-[12px] text-[#636366]">机构</span>
              <select
                value={institution}
                onChange={(event) => {
                  surveyDraftRef.current.institution = event.target.value;
                  setInstitution(event.target.value);
                }}
                className="h-11 w-full rounded-lg border border-[#dfe5e2] bg-white px-3 text-[13px] text-[#3a3a3c] outline-none transition-colors focus:border-[#68a98a] focus:ring-2 focus:ring-[#dcefe5]"
              >
                {institutions.map((tenant) => (
                  <option key={tenant} value={tenant}>
                    {tenant}
                  </option>
                ))}
              </select>
            </label>

            {notice && (
              <div
                id="login-notice"
                role="status"
                aria-live="polite"
                className={`rounded-lg border px-3 py-2 text-[12px] ${
                  noticeKind === "success"
                    ? "border-[#ccebd6] bg-[#f3fbf6] text-[#258a3f]"
                    : "border-[#ffd7d7] bg-[#fff5f5] text-[#d93025]"
                }`}
              >
                {notice}
              </div>
            )}

            <div className="flex items-center justify-between gap-2 pt-1">
              {mode === "register" ? (
                <button
                  type="button"
                  onClick={() => {
                    setMode("login");
                    setNotice("");
                    setNoticeKind("error");
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2 py-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
                >
                  <LogIn className="h-3.5 w-3.5" />返回登录
                </button>
              ) : (
                <button
                  type="button"
                  data-registration-entry="true"
                  onClick={() => {
                    setMode("register");
                    setNotice("");
                    setNoticeKind("error");
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2 py-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
                  title="注册新用户"
                >
                  <UserPlus className="h-3.5 w-3.5" />注册新用户
                </button>
              )}
              <div className="ml-auto flex gap-2" data-login-primary-actions="true">
                <button
                  type="button"
                  onClick={cancelAndSaveSurvey}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
                >
                  <X className="h-3.5 w-3.5" />
                  取消
                </button>
                <button
                  type="submit"
                  disabled={(mode === "login" ? !loginReady : !registerReady) || busy}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#0f8554] px-4 py-2 text-[12px] text-white transition-colors hover:bg-[#0c764a] disabled:opacity-40"
                >
                  <Mail className="h-3.5 w-3.5" />
                  {submitting ? "处理中" : mode === "login" ? "登录" : "注册"}
                </button>
              </div>
            </div>
          </form>
        </section>
      </main>
    </div>
  );
}

function looksLikeEmail(value: string) {
  return value.includes("@");
}

function loginSurveyDraft(
  trigger: LoginSurveyTrigger,
  source: { account: string; institution: string; neededMetrics: string; reportUsage: string },
  messageIdRef: { current: string },
): LoginSurveyDraft | null {
  const neededMetrics = source.neededMetrics.trim();
  const reportUsage = source.reportUsage.trim();
  if (!neededMetrics && !reportUsage) return null;
  if (!messageIdRef.current) {
    messageIdRef.current = `mb_${createClientUuid().replaceAll("-", "")}`;
  }
  return {
    messageId: messageIdRef.current,
    account: source.account.trim(),
    institution: source.institution,
    neededMetrics,
    reportUsage,
    trigger,
  };
}

function SurveyQuestion({
  index,
  label,
  value,
  placeholder,
  disabled,
  onChange,
}: {
  index: string;
  label: string;
  value: string;
  placeholder: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-center gap-2 text-[12px] font-medium text-[#28483a]">
        <span className="text-[10px] font-semibold tracking-[0.08em] text-[#0f8554]">{index}</span>
        {label}
      </span>
      <textarea
        value={value}
        maxLength={1000}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-[92px] min-h-[92px] w-full resize-y rounded-xl border border-[#dbe7e0] bg-white/90 px-3.5 py-3 text-[12px] leading-5 text-[#28483a] outline-none transition-colors placeholder:text-[#a4b0aa] focus:border-[#68a98a] focus:ring-2 focus:ring-[#dcefe5] disabled:cursor-not-allowed disabled:bg-white/55 disabled:text-[#9aa6a0]"
      />
      <span className="mt-0.5 block text-right text-[10px] tabular-nums text-[#9ba9a2]">{value.length}/1000</span>
    </label>
  );
}

function LoginInput({
  label,
  value,
  type = "text",
  placeholder,
  autoComplete,
  onChange,
}: {
  label: string;
  value: string;
  type?: string;
  placeholder: string;
  autoComplete?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      <span className="mb-1.5 block text-[12px] text-[#636366]">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        autoComplete={autoComplete}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 w-full rounded-lg border border-[#dfe5e2] bg-white px-3 text-[13px] text-[#3a3a3c] outline-none transition-colors focus:border-[#68a98a] focus:ring-2 focus:ring-[#dcefe5]"
      />
    </label>
  );
}
