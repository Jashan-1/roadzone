import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon.jsx';
import { HIGHWAYS } from './zone.js';


export default function Admin({ open, onClose, onMade, onBusy }) {
  const dlg = useRef(null);
  const [jobs, setJobs] = useState([]);
  const seen = useRef({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: '', where: '', limit_miles: 50, hub_miles: 5, band_step_miles: 10, min_corridor_cells: 30, highways: [] });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  useEffect(() => {
    const d = dlg.current;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  const call = async (url, opts = {}) => {
    let res;
    try {
      res = await fetch(url, opts);
    } catch {
      return { ok: false, body: { error: 'Can’t reach the RoadZone server.' } };
    }
    const body = await res.json().catch(() => ({ error: `Server error ${res.status}` }));
    return { ok: res.ok, body };
  };

  // only new-location jobs: started from this dialog, or still being made (remakes from Map settings belong there)
  const mine = jobs.filter((j) => j.kind === 'new' && (j.job in seen.current || j.state === 'running'));
  const running = mine.some((j) => j.state === 'running');
  const making = mine.find((j) => j.state === 'running');
  useEffect(() => onBusy(making ? `Making zones for ${making.name}…` : null), [making?.job]);

  // while open or while a job runs (even after closing), keep the job list fresh; a finished job is a new location
  useEffect(() => {
    if (!open && !running) return;
    let alive = true;
    const tick = async () => {
      const { ok, body } = await call('/api/jobs');
      if (!alive) return;
      if (!ok) return setError(body.error);
      if (body.some((j) => j.state === 'done' && seen.current[j.job] === 'running')) onMade();
      for (const j of body) if (j.job in seen.current || (j.kind === 'new' && j.state === 'running')) seen.current[j.job] = j.state;
      setJobs(body);
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(id); };
  }, [open, running]);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!form.highways.length) return setError('Pick at least one highway type.');
    setBusy(true);
    const { ok, body } = await call('/api/runs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form, limit_miles: +form.limit_miles, hub_miles: +form.hub_miles,
        band_step_miles: +form.band_step_miles, min_corridor_cells: +form.min_corridor_cells }),
    });
    setBusy(false);
    if (!ok) return setError(body.error);
    seen.current[body.job] = 'running';
    setJobs((j) => [body, ...j]);
  };

  const toggle = (code) => setForm({ ...form, highways: form.highways.includes(code) ? form.highways.filter((h) => h !== code) : [...form.highways, code] });
  return (
    <dialog ref={dlg} onClose={onClose} aria-labelledby="admin-title">
      <form onSubmit={submit}>
        <div className="dlg-head">
          <div style={{ flexGrow: 1 }}>
            <h2 id="admin-title">New location</h2>
            <p>Makes zones for a new dealership.</p>
          </div>
          <button type="button" className="round" aria-label="Close" onClick={onClose}><Icon name="close" size={16} /></button>
        </div>

        <div className="dlg-body">
          <fieldset>
            <legend>Where is the shop?</legend>
            <div className="grid2">
              <div className="field">
                <label htmlFor="aname">Name dealers will see</label>
                <input id="aname" type="text" placeholder="Santa Rosa dealership" value={form.name} onChange={set('name')} maxLength={80} />
              </div>
              <div className="field">
                <label htmlFor="awhere">Shop location (lat, lon)</label>
                <input id="awhere" type="text" placeholder="37.32305, -121.97000" value={form.where} onChange={set('where')} required />
              </div>
            </div>
          </fieldset>

          <fieldset>
            <legend>How far do the vans go? <span>Road miles</span></legend>
            <div className="grid3">
              <div className="field"><label htmlFor="alimit">Furthest served</label><input id="alimit" type="number" min="5" max="80" step="5" value={form.limit_miles} onChange={set('limit_miles')} required /></div>
              <div className="field"><label htmlFor="ahub">Hub (zone 0)</label><input id="ahub" type="number" min="1" max="40" step="1" value={form.hub_miles} onChange={set('hub_miles')} required /></div>
              <div className="field"><label htmlFor="astep">Each ring</label><input id="astep" type="number" min="1" max="50" step="1" value={form.band_step_miles} onChange={set('band_step_miles')} required /></div>
            </div>
          </fieldset>

          <fieldset>
            <legend>Which highways give zones their letters? <span>Pick at least one.</span></legend>
            <div className="chips">
              {HIGHWAYS.map(([code, label]) => (
                <label key={code} className="chip"><input type="checkbox" checked={form.highways.includes(code)} onChange={() => toggle(code)} /> {label}</label>
              ))}
            </div>
          </fieldset>

          <div className="field">
            <label htmlFor="amerge">Join very small zones into a neighbour ({form.min_corridor_cells} map tiles)</label>
            <input id="amerge" type="range" min="0" max="200" step="10" value={form.min_corridor_cells} onChange={set('min_corridor_cells')} />
            <div className="ends"><span>Keep every zone</span><span>Fewer, larger zones</span></div>
          </div>

          {mine.length > 0 && (
            <ul className="jobs" aria-live="polite">
              {mine.map((j) => (
                <li key={j.job}>
                  <div><span>{j.name}</span>{j.error && <pre>{j.error}</pre>}</div>
                  <span>{{ running: 'Making zones…', done: 'Ready in the location list', failed: 'Failed' }[j.state]}</span>
                </li>
              ))}
            </ul>
          )}
          {error && <p className="form-error" role="alert">{error}</p>}
        </div>

        <div className="dlg-foot">
          <p>Takes a few minutes. Map data covers California only.</p>
          <button type="button" className="plain" onClick={onClose}>Close</button>
          <button type="submit" className="primary" disabled={busy || running}>{running ? 'Making zones…' : 'Make zones'}</button>
        </div>
      </form>
    </dialog>
  );
}
