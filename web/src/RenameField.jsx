import { useEffect, useState } from 'react';

/** The location's name, editable in place. Saving renames every run of the location (Streamlit shows it too). */
export default function RenameField({ name, run, onRenamed }) {
  const [draft, setDraft] = useState(name);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setDraft(name); setError(''); }, [name]);
  const changed = draft.trim() && draft.trim() !== name;

  const save = async (e) => {
    e.preventDefault();
    if (!changed || saving) return;
    setSaving(true);
    setError('');
    try {
      const res = await fetch('/api/rename', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run, name: draft }) });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `Server error ${res.status}`);
      await onRenamed(name, body.name);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="field rename" onSubmit={save}>
      <label htmlFor="loc-name">Location name</label>
      <div className="rename-row">
        <input id="loc-name" type="text" value={draft} maxLength={80} autoComplete="off" data-1p-ignore
          onChange={(e) => { setDraft(e.target.value); setError(''); }} />
        {changed && <button type="submit" className="go" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>}
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
    </form>
  );
}
