import { useState } from "react";
import { login, signup } from "../api";

export default function Login({ onAuthed }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data =
        mode === "login"
          ? await login(email, password)
          : await signup(email, password, workspace || "My Workspace");
      localStorage.setItem("ih_token", data.access_token);
      localStorage.setItem("ih_role", data.role || "admin");
      onAuthed(data.role || "admin");
    } catch (err) {
      setError(err?.response?.data?.detail || "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="auth-logo">◧</span> InsightHub
        </div>
        <p className="auth-tag">Upload your data. See it. Ask it. Every number traceable.</p>

        <div className="auth-switch">
          <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")} type="button">
            Log in
          </button>
          <button className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")} type="button">
            Sign up
          </button>
        </div>

        <form onSubmit={submit} className="auth-form">
          {mode === "signup" && (
            <label>
              Company / workspace name
              <input value={workspace} onChange={(e) => setWorkspace(e.target.value)} placeholder="Acme Corp" />
            </label>
          )}
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@company.com" />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              placeholder={mode === "signup" ? "min 8 characters" : ""}
            />
          </label>
          {error && <div className="auth-error">{error}</div>}
          <button className="auth-submit" disabled={busy} type="submit">
            {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create workspace"}
          </button>
        </form>
      </div>
    </div>
  );
}
