import { useEffect, useMemo, useRef, useState } from 'react';
import ZoneMap from './ZoneMap.jsx';
import Admin from './Admin.jsx';
import ZoneSettings from './ZoneSettings.jsx';
import HowItWorks from './HowItWorks.jsx';
import { Icon } from './Icon.jsx';
import { bandRange, bookingNote, reviewNote, script, shortPlace, spoken, verdict, viaZone } from './zone.js';

const TITLES = { in: 'In service area', review: 'Needs a double-check', out: 'Outside service area' };
const SHORT = { in: 'In area', review: 'Double-check', out: 'Out of area' };
const BADGE = { in: 'check', review: 'alert', out: 'close' };

// per-viewer conveniences only: never needed for a correct answer
function read(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } }
function write(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private mode */ } }

async function getJSON(url, signal) {
  const res = await fetch(url, { signal });
  const body = await res.json().catch(() => ({ error: `Server error ${res.status}` }));
  if (!res.ok) throw new Error(body.error || `Server error ${res.status}`);
  return body;
}

const zoneSort = (a, b) => parseInt(a, 10) - parseInt(b, 10) || a.localeCompare(b);

export default function App() {
  const [locations, setLocations] = useState(null);
  const [run, setRun] = useState(read('rz-run', ''));
  const [zones, setZones] = useState(null);
  const [query, setQuery] = useState('');
  const [state, setState] = useState({ status: 'idle' });
  const [history, setHistory] = useState(read('rz-history', []));
  const [copied, setCopied] = useState('');
  const [focus, setFocus] = useState('');
  const [opacity, setOpacity] = useState(70); // Streamlit's default colour strength
  const [colourBy, setColourBy] = useState(read('rz-colour', 'zones'));
  const pickColour = (c) => { setColourBy(c); write('rz-colour', c); };
  const [theme, setTheme] = useState(read('rz-theme', null) ?? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const flipTheme = () => setTheme((t) => { const next = t === 'dark' ? 'light' : 'dark'; write('rz-theme', next); return next; });
  const [admin, setAdmin] = useState(false);
  const [help, setHelp] = useState(false);
  const [about, setAbout] = useState(false);
  const [loadError, setLoadError] = useState('');
  const pending = useRef(null);
  const input = useRef(null);

  // `prefer`: a run just made; otherwise keep the current run if it still exists
  const refreshLocations = (prefer) => getJSON('/api/locations').then((l) => {
    setLocations(l);
    setLoadError('');
    const has = (r) => l.some((s) => s.variants.some((v) => v.run === r));
    setRun((r) => (prefer && has(prefer) ? prefer : has(r) ? r : l.at(-1)?.run ?? ''));
  }).catch((e) => setLoadError(e.message));
  useEffect(() => { refreshLocations(); }, []);

  const shop = locations?.find((s) => s.variants.some((x) => x.run === run));
  const variant = shop?.variants.find((x) => x.run === run);
  const loc = shop && { ...variant, name: shop.name };
  useEffect(() => {
    if (!run) return;
    write('rz-run', run);
    setZones(null);
    setFocus('');
    const ctl = new AbortController();
    getJSON(`/api/zones?run=${encodeURIComponent(run)}`, ctl.signal).then(setZones).catch((e) => e.name !== 'AbortError' && setLoadError(e.message));
    return () => ctl.abort();
  }, [run]);

  const reset = () => {
    pending.current?.abort();
    setState({ status: 'idle' });
    setQuery('');
    input.current?.focus();
  };

  const check = async (q) => {
    q = q.trim();
    if (!q || !run) return;
    pending.current?.abort();
    const ctl = new AbortController();
    pending.current = ctl;
    setQuery(q);
    setCopied('');
    setState({ status: 'loading' });
    try {
      const r = await getJSON(`/zone?run=${encodeURIComponent(run)}&q=${encodeURIComponent(q)}`, ctl.signal);
      const v = verdict(r);
      setState({ status: 'done', r, v });
      const place = shortPlace(r.label) || q;
      const entry = { q, run, shop: loc?.name, v, code: r.zone || '—', title: place.split(',')[0], sub: [SHORT[v], ...place.split(',').slice(1)].join(' · ') };
      setHistory((h) => {
        const next = [entry, ...h.filter((x) => !(x.q === q && (x.shop ?? x.run) === (loc?.name ?? run)))].slice(0, 5);
        write('rz-history', next);
        return next;
      });
    } catch (e) {
      if (e.name !== 'AbortError') setState({ status: 'error', message: e.message });
    }
  };

  // removes these entries from this browser's history (only ever stored here, never on the server)
  const forget = (items) => setHistory((h) => {
    const next = h.filter((x) => !items.includes(x));
    write('rz-history', next);
    return next;
  });

  const copy = (text, key) => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(''), 1600);
    }).catch(() => {});
  };

  const codes = useMemo(() => (zones ? zones.features.map((f) => f.properties.zone).sort(zoneSort) : []), [zones]);
  const recent = history.filter((h) => (h.shop ? h.shop === loc?.name : h.run === run));
  const { status, r, v } = state;
  const limit = loc?.limit_miles ?? 50;
  const facts = r && [
    ['Road miles', r.miles ?? '—'],
    ...(v === 'out' ? [['Our limit', `${limit} road mi`]] : [
      ['Band', r.band != null ? [r.band === 0 ? 'Hub' : r.band, bandRange(r.band, loc ?? zones?.coverage ?? {})].filter(Boolean).join(' · ') : '—'],
      ['Corridor', r.corridor && r.corridor !== '-' ? r.corridor : '—'],
      ...(viaZone(r.zone) ? [['Via zone', viaZone(r.zone)]] : []),
    ]),
  ];

  return (
    <>
      <header className="top">
        <div className="brand">
          <span className="brand-mark" style={{ color: '#000000' }}><Icon name="logo" size={20} width={2.4} /></span>
          <span className="brand-name">RoadZone</span>
          <span className="brand-sub">Service desk</span>
        </div>
        <label htmlFor="loc" className="sr">Location</label>
        <div className="loc">
          <span className="dot" />
          <select id="loc" className="ell" value={shop?.name ?? ''} disabled={!locations?.length}
            onChange={(e) => { setRun(locations.find((s) => s.name === e.target.value).run); reset(); }}>
            {(locations ?? []).map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
        </div>
        <button type="button" className="round" aria-label="How RoadZone works" onClick={() => setAbout(true)}><Icon name="help" size={20} width={2} /></button>
        <button type="button" className="round" aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} onClick={flipTheme}>
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={20} width={2} />
        </button>
        <button type="button" className="round" aria-label="Admin: make zones for a new location" onClick={() => setAdmin(true)}><Icon name="sliders" size={20} width={2} /></button>
      </header>

      <main>
        <section className="panel" aria-label="Address check">
          <div>
            <p className="area">{loc ? `${loc.name} · ${loc.limit_miles} road-mile service area` : ' '}</p>
            <h1>Which zone is an address in?</h1>
          </div>

          {loadError && (
            <div className="card error" role="alert">
              <Icon name="info" />
              <div><strong>Can’t load zones</strong><p>{loadError}</p></div>
            </div>
          )}
          {locations?.length === 0 && (
            <p className="empty">No locations have zones yet. An admin can make them from the settings button at the top right.</p>
          )}

          <form className="search" onSubmit={(e) => { e.preventDefault(); check(query); }}>
            <div className="field">
              <div className="label-row">
                <label htmlFor="q">Address or coordinates</label>
                <button type="button" className="info" aria-label="What can I type here?" aria-expanded={help} aria-controls="q-help" onClick={() => setHelp(!help)}>
                  <Icon name="info" size={16} width={2} />
                </button>
              </div>
              <div className="query">
                <input id="q" ref={input} type="text" value={query} autoComplete="off" autoFocus maxLength={300}
                  placeholder="37.4419, -122.1430" aria-describedby="q-help" onChange={(e) => setQuery(e.target.value)} />
                {query && <button type="button" className="round" aria-label="Clear" onClick={reset}><Icon name="close" size={14} width={2.8} /></button>}
              </div>
              <p id="q-help" className="help" hidden={!help}>Paste coordinates from Google Maps (e.g. 37.3230, -121.9700) or type an address. Typed addresses are looked up on OpenStreetMap, an outside website; coordinates stay here.</p>
            </div>
            <button type="submit" className="go" disabled={!query.trim() || !run || status === 'loading'}>
              Check <Icon name="arrow" width={2.4} />
            </button>
          </form>

          {status === 'loading' && (
            <div className="card loading" role="status">
              <strong>Tracing the road route from {loc?.name}…</strong>
              <div className="bar"><span /></div>
              <div className="ghosts"><span /><span /><span /></div>
            </div>
          )}

          {status === 'error' && (
            <div className="card error" role="alert">
              <Icon name="info" />
              <div>
                <strong>{/could not find/.test(message(state)) ? 'Couldn’t find that address' : 'That check didn’t work'}</strong>
                <p>{/could not find/.test(message(state)) ? 'Check the spelling, add the town, or paste lat, lon from Google Maps.' : message(state)}</p>
              </div>
            </div>
          )}

          {status === 'done' && (
            <article className={`card ${v}`} role="status">
              <div className="verdict">
                <span className="badge"><Icon name={BADGE[v]} width={2.8} /></span>
                <div className="what">
                  <div className="title">{TITLES[v]}</div>
                  <div className="place ell">{shortPlace(r.label)}</div>
                </div>
                <button type="button" className="round" aria-label="Start a new check" onClick={reset}><Icon name="close" size={16} width={2.6} /></button>
              </div>
              <div className="result-body">
                {r.zone && (
                  <div className="zone">
                    <div>
                      <div className="zone-label">Service zone</div>
                      <div className="zone-code">{r.zone}</div>
                      <div className="zone-say">Say it as “{spoken(r.zone)}”</div>
                    </div>
                    <button type="button" className="pill" onClick={() => copy(r.zone, 'zone')}><Icon name="copy" size={16} width={2} />{copied === 'zone' ? 'Copied' : 'Copy'}</button>
                  </div>
                )}
                <div className="script">
                  <div className="script-label"><Icon name="speech" size={15} width={2} />Say to the customer</div>
                  <p>“{script(v, r, limit)}”</p>
                </div>
                {v === 'review' && (
                  <div className="note"><Icon name="warn" size={20} width={2} /><p>{reviewNote(r)}</p></div>
                )}
                <dl className="facts">
                  {facts.map(([k, val]) => <div key={k}><dt>{k}</dt><dd className="ell">{val}</dd></div>)}
                </dl>
                <div className="actions">
                  {v !== 'out' && <button type="button" className="primary" onClick={() => copy(bookingNote(v, r), 'note')}>{copied === 'note' ? 'Booking note copied' : 'Copy booking note'}</button>}
                  <button type="button" className={v === 'out' ? 'primary' : ''} onClick={reset}>New check</button>
                </div>
              </div>
            </article>
          )}

          {status !== 'loading' && recent.length > 0 && (
            <div className="list">
              <div className="list-head">
                <h2>Recent checks</h2>
                <button type="button" className="link" onClick={() => forget(recent)}>Clear</button>
              </div>
              {recent.map((h) => (
                <div key={h.q} className={`row-wrap ${h.v}`}>
                  <button type="button" className="row" onClick={() => check(h.q)}>
                    <span className="row-code">{h.code}</span>
                    <span className="row-text"><span className="row-title ell">{h.title}</span><span className="row-sub ell">{h.sub}</span></span>
                    <Icon name="history" size={16} width={2} />
                  </button>
                  <button type="button" className="row-x" aria-label={`Remove ${h.title} from recent checks`} onClick={() => forget([h])}>
                    <Icon name="close" size={14} width={2.4} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <details>
            <summary>Map settings <Icon name="chevron" width={2} /></summary>
            <div className="settings">
              {shop && <ZoneSettings shop={shop} variant={variant} onPick={setRun} onMade={refreshLocations} />}
              <div className="field">
                <label htmlFor="focus">Show</label>
                <select id="focus" value={focus} onChange={(e) => setFocus(e.target.value)}>
                  <option value="">All zones</option>
                  {codes.map((c) => <option key={c} value={c}>Zone {c}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="opacity">Colour strength ({opacity}%)</label>
                <input id="opacity" type="range" min="10" max="100" step="5" value={opacity} onChange={(e) => setOpacity(+e.target.value)} />
              </div>
            </div>
          </details>
        </section>

        <ZoneMap onHelp={() => setAbout(true)} colourBy={colourBy} onColourBy={pickColour} zones={zones} name={loc?.name ?? 'RoadZone'} opacity={opacity} focus={focus} theme={theme}
          point={status === 'done' && r.lon != null ? [r.lon, r.lat] : null}
          highlight={status === 'done' ? r.zone : ''} />
      </main>

      <HowItWorks open={about} onClose={() => setAbout(false)} loc={loc} />
      <Admin open={admin} onClose={() => setAdmin(false)} onMade={refreshLocations} />
    </>
  );
}

function message(s) { return s.message || ''; }
