import { useEffect, useRef, useState } from 'react';
import { HIGHWAYS, sameSettings } from './zone.js';

const pick = (v) => ({ limit_miles: v.limit_miles, hub_miles: v.hub_miles, band_step_miles: v.band_step_miles,
  highways: v.highways, min_corridor_cells: v.min_corridor_cells });

/** The run's settings, editable. A mix this shop already has is shown at once; a new mix is made on request. */
export default function ZoneSettings({ shop, variant, onPick, onMade }) {
  const [draft, setDraft] = useState(pick(variant));
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');
  const timer = useRef(null);
  useEffect(() => setDraft(pick(variant)), [variant.run]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const num = { limit_miles: +draft.limit_miles, hub_miles: +draft.hub_miles, band_step_miles: +draft.band_step_miles,
    highways: draft.highways, min_corridor_cells: +draft.min_corridor_cells };
  const match = shop.variants.find((v) => sameSettings(v, num));
  useEffect(() => { if (match && match.run !== variant.run) onPick(match.run); }, [match?.run]);

  const set = (k) => (e) => { setError(''); setDraft({ ...draft, [k]: e.target.value }); };
  const toggle = (code) => setDraft({ ...draft,
    highways: HIGHWAYS.map(([c]) => c).filter((c) => (c === code) !== draft.highways.includes(c)) });

  // a mix that already has zones is never a problem (old runs may not have recorded their highway types)
  const problem = match ? '' : !draft.highways.length ? 'Tick at least one highway type to see zones.'
    : !(num.hub_miles < num.limit_miles) ? 'The Hub must be smaller than the furthest distance.' : '';

  const watch = (id) => {
    timer.current = setTimeout(async () => {
      const list = await fetch('/api/jobs').then((r) => r.json()).catch(() => []);
      const j = Array.isArray(list) && list.find((x) => x.job === id);
      if (!j || j.state === 'running') return watch(id);
      setJob(null);
      if (j.state === 'failed') setError(j.error || 'Making zones failed.');
      else onMade(j.run);
    }, 4000);
  };

  const make = async () => {
    setError('');
    const res = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_run: variant.run, ...num }) }).catch(() => null);
    const body = await res?.json().catch(() => ({})) ?? { error: 'Can’t reach the RoadZone server.' };
    if (!res?.ok) return setError(body.error || `Server error ${res.status}`);
    setJob(body.job);
    watch(body.job);
  };

  const far = num.limit_miles > variant.limit_miles;
  return (
    <>
      <fieldset>
        <legend>How far do the vans go? <span>Road miles</span></legend>
        <div className="grid3">
          <div className="field"><label htmlFor="slimit">Furthest served</label><input id="slimit" type="number" min="5" max="80" step="5" value={draft.limit_miles} onChange={set('limit_miles')} /></div>
          <div className="field"><label htmlFor="shub">Hub (zone 0)</label><input id="shub" type="number" min="1" max="40" step="1" value={draft.hub_miles} onChange={set('hub_miles')} /></div>
          <div className="field"><label htmlFor="sstep">Each ring</label><input id="sstep" type="number" min="1" max="50" step="1" value={draft.band_step_miles} onChange={set('band_step_miles')} /></div>
        </div>
      </fieldset>

      <fieldset>
        <legend>Which highways give zones their letters?</legend>
        <div className="chips">
          {HIGHWAYS.map(([code, label]) => (
            <label key={code} className="chip"><input type="checkbox" checked={draft.highways.includes(code)} onChange={() => toggle(code)} /> {label}</label>
          ))}
        </div>
      </fieldset>

      <div className="field">
        <label htmlFor="smerge">Join very small zones into a neighbour ({draft.min_corridor_cells} map tiles)</label>
        <input id="smerge" type="range" min="0" max="200" step="10" value={draft.min_corridor_cells} onChange={set('min_corridor_cells')} />
        <div className="ends"><span>Keep every zone</span><span>Fewer, larger zones</span></div>
      </div>

      {problem && <p className="help" role="status">{problem}</p>}
      {!problem && !match && (
        <div className="remake" role="status">
          <p>{job ? (far ? 'Driving the new, further roads. This takes a few minutes…' : 'Making zones…')
            : 'There are no zones with these settings yet.'}</p>
          {!job && <button type="button" className="go" onClick={make}>Make zones</button>}
          {!job && <button type="button" className="plain" onClick={() => setDraft(pick(variant))}>Undo changes</button>}
        </div>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
    </>
  );
}
