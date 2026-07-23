import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/authStore";
import { Icon } from "@/components/ui";
import { StepLogo } from "@/components/brand/StepLogo";

export default function Login() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    document.title = "Masuk — STEP";
    return () => { document.title = "STEP — Sales Team Execution Platform"; };
  }, []);

  // ─────────────────────────────────────────────────────────────
  // Business logic unchanged — UI/branding only.
  // ─────────────────────────────────────────────────────────────
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { username, password });
      login(data.access_token, data.user);
      navigate("/dashboard");
    } catch {
      setError("Username atau password salah.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden flex items-center justify-center px-4 py-10
                    bg-gradient-to-b from-white via-brand-50 to-brand-100">
      {/* ── Animated background: soft floating blobs ── */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-24 -left-24 w-[28rem] h-[28rem] rounded-full bg-brand-300/40 blur-3xl animate-blob" />
        <div className="absolute top-1/3 -right-32 w-[32rem] h-[32rem] rounded-full bg-brand-400/30 blur-3xl animate-blob-slow" style={{ animationDelay: "-8s" }} />
        <div className="absolute -bottom-32 left-1/4 w-[26rem] h-[26rem] rounded-full bg-brand-200/50 blur-3xl animate-blob" style={{ animationDelay: "-14s" }} />
        {/* faint dotted texture */}
        <div
          className="absolute inset-0 opacity-[0.04]"
          style={{ backgroundImage: "radial-gradient(#2884d1 1px, transparent 1px)", backgroundSize: "26px 26px" }}
        />
      </div>

      <main className="relative z-10 w-full max-w-sm flex flex-col items-center">
        {/* ── Hero / brand lockup ── */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className="animate-float">
            <StepLogo size={64} className="drop-shadow-[0_12px_24px_rgba(92,184,255,0.5)] animate-fade-up" title="STEP logo" />
          </div>

          <h1
            className="mt-5 text-6xl sm:text-7xl font-extrabold tracking-tight leading-none
                       bg-gradient-to-br from-brand-700 via-brand-600 to-brand-400 bg-clip-text text-transparent
                       animate-fade-up"
            style={{ animationDelay: "80ms" }}
          >
            STEP
          </h1>

          <p
            className="mt-3 text-[0.8rem] font-semibold uppercase tracking-[0.18em] text-brand-700 animate-fade-up"
            style={{ animationDelay: "150ms" }}
          >
            Sales Team Execution Platform
          </p>

          <p
            className="mt-3 max-w-xs text-sm leading-relaxed text-slate-500 animate-fade-up"
            style={{ animationDelay: "220ms" }}
          >
            Empowering sales teams to execute, monitor, and optimize
            every step of the call.
          </p>

          <p className="mt-4 text-xs text-slate-400 animate-fade-up" style={{ animationDelay: "300ms" }}>
            by <span className="font-semibold text-slate-500">Skintific</span>
          </p>
        </div>

        {/* ── Login card (glassmorphism) ── */}
        <div
          className="w-full rounded-3xl border border-white/70 bg-white/70 backdrop-blur-xl shadow-glass p-8 animate-fade-up"
          style={{ animationDelay: "380ms" }}
        >
          <h2 className="text-slate-800 font-semibold text-base mb-6">Masuk ke akun Anda</h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="username" className="form-label">Username</label>
              <input
                id="username"
                className="input rounded-xl bg-white/80 focus:ring-brand-500/30 focus:border-brand-400"
                placeholder="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="form-label">Password</label>
              <div className="relative">
                <input
                  id="password"
                  type={showPw ? "text" : "password"}
                  className="input rounded-xl bg-white/80 pr-10 focus:ring-brand-500/30 focus:border-brand-400"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowPw((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-brand-600 transition-colors"
                  aria-label={showPw ? "Sembunyikan password" : "Tampilkan password"}
                >
                  <Icon name={showPw ? "eye-slash" : "eye"} className="w-4 h-4" />
                </button>
              </div>
            </div>

            {error && (
              <div role="alert" className="alert-danger text-sm py-2.5 animate-slide-down">
                <Icon name="exclamation-circle" className="w-4 h-4 shrink-0" aria-hidden={true} />
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-xl py-3 mt-2 font-semibold text-white
                         bg-gradient-to-br from-brand-500 to-brand-700
                         shadow-brand hover:shadow-brand-lg hover:-translate-y-0.5 active:translate-y-0
                         transition-all duration-200
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2
                         disabled:opacity-60 disabled:pointer-events-none"
            >
              {loading ? (
                <span className="flex items-center gap-2 justify-center">
                  <Icon name="arrow-path" className="w-4 h-4 animate-spin" />
                  Memuat...
                </span>
              ) : (
                <span className="flex items-center gap-1.5 justify-center">
                  Masuk
                  <Icon name="chevron-right" className="w-4 h-4" />
                </span>
              )}
            </button>
          </form>

          <p className="text-xs text-slate-400 text-center mt-6">
            Hubungi HO Admin jika akun belum dibuat
          </p>
        </div>

        <p className="text-slate-400 text-xs text-center mt-6">
          Hanya untuk Penggunaan Internal · by <span className="font-medium text-slate-500">Skintific</span>
        </p>
      </main>
    </div>
  );
}
