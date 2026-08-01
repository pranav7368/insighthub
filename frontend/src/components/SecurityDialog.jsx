import { useEffect, useState } from "react";
import {
  disableMfa, downloadMyData, enableMfa, errorText, getMfaStatus,
  revokeSessions, startMfaSetup,
} from "../api";

/**
 * Account & security: the second factor, session control, and the personal
 * data export.
 *
 * All three existed only as API endpoints, which meant nobody could actually
 * use them. Grouped here because they answer the same three questions a person
 * asks about their own account: is it protected, who else is signed in, and
 * what do you hold about me.
 */
export default function SecurityDialog({ onClose, onSignedOut }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // enrolment is a short wizard: idle -> setup (scan) -> codes (save these)
  const [stage, setStage] = useState("idle");
  const [enrolment, setEnrolment] = useState(null);   // {secret, otpauth_uri}
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState(null);
  const [password, setPassword] = useState("");

  const load = () => getMfaStatus().then(setStatus)
    .catch((err) => setError(errorText(err, "Could not load your security settings.")));

  useEffect(() => { load(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const begin = async () => {
    setBusy(true); setError(null);
    try {
      setEnrolment(await startMfaSetup());
      setStage("setup");
    } catch (err) { setError(errorText(err, "Could not start setup.")); }
    finally { setBusy(false); }
  };

  const confirm = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const res = await enableMfa(code.trim());
      setRecoveryCodes(res.recovery_codes);
      setStage("codes");
      setCode("");
      await load();
    } catch (err) { setError(errorText(err, "That code was not accepted.")); }
    finally { setBusy(false); }
  };

  const turnOff = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await disableMfa(password);
      setPassword("");
      setStage("idle");
      setRecoveryCodes(null);
      await load();
    } catch (err) { setError(errorText(err, "Could not turn it off.")); }
    finally { setBusy(false); }
  };

  const signOutEverywhere = async () => {
    setBusy(true); setError(null);
    try {
      await revokeSessions();
      onSignedOut();          // this session is ended too — that is the point
    } catch (err) { setError(errorText(err, "Could not sign out.")); setBusy(false); }
  };

  const exportMine = async () => {
    setError(null);
    try { await downloadMyData(); }
    catch (err) { setError(errorText(err, "Could not prepare your download.")); }
  };

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Account &amp; security</h3>
          <button onClick={onClose} disabled={busy}>Close</button>
        </div>

        {error && <div className="tpl-error">{error}</div>}

        {/* ------------------------------------------- two-factor ------- */}
        <div className="section-title">Two-factor authentication</div>

        {stage === "idle" && (
          <>
            <p className="access-note">
              {status?.enabled
                ? "On — you'll be asked for a code from your authenticator app when you sign in."
                : "Off. A password alone is one stolen phrase away from your data."}
            </p>
            {status?.enabled ? (
              <>
                <p className="access-note">
                  {status.recovery_codes_remaining} recovery code
                  {status.recovery_codes_remaining === 1 ? "" : "s"} left.
                </p>
                <form className="sec-inline" onSubmit={turnOff}>
                  <input type="password" value={password} placeholder="Confirm your password"
                    onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
                  <button className="views-btn views-btn--danger" type="submit" disabled={busy}>
                    Turn off
                  </button>
                </form>
              </>
            ) : (
              <button className="views-btn views-btn--accent" onClick={begin} disabled={busy}>
                {busy ? "Starting…" : "Turn on two-factor"}
              </button>
            )}
          </>
        )}

        {stage === "setup" && enrolment && (
          <>
            <p className="access-note">
              Add this to your authenticator app (1Password, Authy, Google Authenticator…),
              then enter the 6-digit code it shows.
            </p>
            <div className="sec-secret">
              <span className="sec-secret__label">Setup key</span>
              <code>{enrolment.secret}</code>
              <button className="views-btn" type="button"
                onClick={() => navigator.clipboard?.writeText(enrolment.secret)}>Copy</button>
            </div>
            <details className="access-more">
              <summary>Or paste this link into your app</summary>
              <code className="sec-uri">{enrolment.otpauth_uri}</code>
            </details>
            <form className="sec-inline" onSubmit={confirm}>
              <input value={code} onChange={(e) => setCode(e.target.value)}
                placeholder="123456" inputMode="numeric" autoComplete="one-time-code"
                maxLength={6} aria-label="6-digit code" autoFocus />
              <button className="views-btn views-btn--accent" type="submit" disabled={busy}>
                {busy ? "Checking…" : "Confirm"}
              </button>
              <button className="views-btn" type="button" onClick={() => setStage("idle")}>
                Cancel
              </button>
            </form>
          </>
        )}

        {stage === "codes" && recoveryCodes && (
          <>
            <p className="access-note">
              <b>Two-factor is on.</b> Save these recovery codes somewhere safe — each works
              once, and they are the way back in if you lose your phone. They are stored
              hashed, so this is the only time they can be shown.
            </p>
            <ul className="sec-codes">
              {recoveryCodes.map((c) => <li key={c}><code>{c}</code></li>)}
            </ul>
            <div className="sec-inline">
              <button className="views-btn" type="button"
                onClick={() => navigator.clipboard?.writeText(recoveryCodes.join("\n"))}>
                Copy all
              </button>
              <button className="views-btn views-btn--accent" onClick={() => setStage("idle")}>
                I've saved them
              </button>
            </div>
          </>
        )}

        {/* ---------------------------------------------- sessions ------- */}
        <div className="section-title access-section">Sessions</div>
        <p className="access-note">
          Signs you out on every device, including this one. Use it if you have lost a
          laptop or think someone else has your password.
        </p>
        <button className="views-btn" onClick={signOutEverywhere} disabled={busy}>
          Sign out everywhere
        </button>

        {/* ------------------------------------------ personal data ------ */}
        <div className="section-title access-section">Your data</div>
        <p className="access-note">
          Download everything held about your account — your profile and your activity —
          as JSON.
        </p>
        <button className="views-btn" onClick={exportMine}>Download my data</button>
      </div>
    </div>
  );
}
