import { useRef, useState } from "react";

export default function UploadButton({ onUpload }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await onUpload(file);
    } catch (err) {
      setError(err?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="upload-button">
      <button onClick={() => inputRef.current?.click()} disabled={busy}>
        {busy ? "Uploading…" : "+ Upload data"}
      </button>
      <input ref={inputRef} type="file" accept=".csv,.xlsx,.xlsm,.pdf,.docx,.txt,.md" hidden onChange={handleChange} />
      {error && <div className="upload-error">{error}</div>}
    </div>
  );
}
