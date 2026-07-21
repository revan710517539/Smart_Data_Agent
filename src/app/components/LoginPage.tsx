import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { Landmark, LogIn, Mail, UserPlus, X } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { beginEnterpriseLogin, loginWithEmail, registerWithEmail } from "../services/authApi";
import { ApiRequestError, apiErrorMessage } from "../services/apiClient";

export function LoginPage() {
  const navigate = useNavigate();
  const { institutions, isAuthenticated, login } = usePlatformContext();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [institution, setInstitution] = useState(institutions[0] || "");
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (isAuthenticated) navigate("/", { replace: true });
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    if (!institutions.length) return;
    if (!institution || !institutions.includes(institution)) {
      setInstitution(institutions[0]);
    }
  }, [institution, institutions]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setNotice("");
    setSubmitting(true);
    try {
      const session =
        mode === "login"
          ? await loginWithEmail({ email, institution })
          : await registerWithEmail({ name, email, institution });
      login(session);
      navigate("/", { replace: true });
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
    setName("");
    setNotice("");
    setMode("login");
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f8f8fa] px-4">
      <div className="w-full max-w-[440px] rounded-2xl border border-[#e5e5ea] bg-white shadow-xl shadow-black/[0.06]">
        <div className="border-b border-[#f0f0f2] px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#1d1d1f]">
              <Landmark className="h-4 w-4 text-white" />
            </div>
            <div>
              <h1 className="text-[17px] tracking-tight text-[#1d1d1f]">Data Agent</h1>
              <p className="mt-0.5 text-[12px] text-[#8a8a8e]">
                {mode === "login" ? "邮箱登录后进入机构工作台" : "注册后默认成为所选机构操作员"}
              </p>
            </div>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-4 px-6 py-5">
          {mode === "register" && (
            <LoginInput label="姓名" value={name} onChange={setName} placeholder="请输入姓名" />
          )}
          <LoginInput label="邮箱" value={email} onChange={setEmail} placeholder="name@bank.com" type="email" />
          <label>
            <span className="mb-1.5 block text-[12px] text-[#636366]">机构</span>
            <select
              value={institution}
              onChange={(event) => setInstitution(event.target.value)}
              className="h-10 w-full rounded-lg border border-[#e5e5ea] bg-white px-3 text-[13px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
            >
              {institutions.map((tenant) => (
                <option key={tenant} value={tenant}>
                  {tenant}
                </option>
              ))}
            </select>
          </label>

          {notice && (
            <div className="rounded-lg border border-[#ffd7d7] bg-[#fff5f5] px-3 py-2 text-[12px] text-[#d93025]">
              {notice}
            </div>
          )}

          <div className="flex items-center justify-between gap-2 pt-1">
            <button
              type="button"
              onClick={() => {
                setMode((current) => (current === "login" ? "register" : "login"));
                setNotice("");
              }}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
            >
              {mode === "login" ? <UserPlus className="h-3.5 w-3.5" /> : <LogIn className="h-3.5 w-3.5" />}
              {mode === "login" ? "注册新用户" : "返回登录"}
            </button>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={cancel}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
              >
                <X className="h-3.5 w-3.5" />
                取消
              </button>
              <button
                type="submit"
                disabled={!email.trim() || (mode === "register" && !name.trim()) || submitting}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-4 py-2 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-40"
              >
                <Mail className="h-3.5 w-3.5" />
                {submitting ? "处理中" : mode === "login" ? "登录" : "注册"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

function LoginInput({
  label,
  value,
  type = "text",
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  type?: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      <span className="mb-1.5 block text-[12px] text-[#636366]">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-lg border border-[#e5e5ea] bg-white px-3 text-[13px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
      />
    </label>
  );
}
