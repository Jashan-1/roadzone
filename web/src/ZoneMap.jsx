import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import { bandRange, corridorColour, legend, shade, zoneColour } from './zone.js';
import { Icon } from './Icon.jsx';

// OpenFreeMap: free vector tiles, no key, commercial use allowed
const STYLE = { light: 'https://tiles.openfreemap.org/styles/positron', dark: 'https://tiles.openfreemap.org/styles/dark' };
const stacked = window.matchMedia('(min-width: 601px) and (max-width: 900px)'); // tablet: panel above map, page scrolls
const phone = window.matchMedia('(max-width: 600px)'); // full-screen map under floating controls and a bottom sheet

/** Keep fitted areas clear of what floats over the map (phone: top controls and the bottom sheet). */
function pad(base) {
  if (!phone.matches) return base;
  const sheet = document.querySelector('.panel')?.getBoundingClientRect().height ?? 200;
  return { top: 130, bottom: Math.min(sheet, window.innerHeight * 0.6) + 24, left: 32, right: 80 };
}

function bounds(fc, extra = []) {
  const b = new maplibregl.LngLatBounds();
  for (const f of fc?.features ?? []) {
    const g = f.geometry;
    const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
    for (const poly of polys) for (const [x, y] of poly[0]) b.extend([x, y]); // outer rings are enough
  }
  if (fc?.base) b.extend(fc.base); // null when only one zone should fill the view
  for (const p of extra) b.extend(p);
  return b;
}

/** Popup body for one zone, built as DOM text (zone data never becomes HTML). */
function zoneCard(p, coverage) {
  const el = document.createElement('div');
  el.className = 'zone-pop';
  const add = (tag, text) => { const n = document.createElement(tag); n.textContent = text; el.append(n); };
  add('strong', p.zone === '0' ? 'Hub (zone 0)' : `Zone ${p.zone}`);
  const range = bandRange(p.band, coverage);
  if (p.band) add('span', `Ring ${p.band}${range ? ` · ${range} road mi` : ''}`);
  else if (range) add('span', `${range} road mi from the dealer`);
  if (p.road && p.corridor !== 'HUB') add('span', p.corridor === 'L' ? 'Local roads, off the lettered highways' : `Along ${p.road}`);
  return el;
}

export default function ZoneMap({ busy, zones, name, point, pointTag, highlight, focus, opacity, theme, colourBy, onColourBy, onHelp }) {
  const box = useRef(null);
  const map = useRef(null);
  const marks = useRef({});
  const shown = useRef(theme);
  const latest = useRef(zones);
  latest.current = zones;
  const scheme = theme;
  const [ready, setReady] = useState(0);
  const [full, setFull] = useState(false);
  // auto-hiding controls: fade after 2 s without activity on the map, back on any touch, swipe, mouse or focus
  const [quiet, setQuiet] = useState(false);
  const quietTimer = useRef(null);
  const wake = () => {
    setQuiet(false);
    clearTimeout(quietTimer.current);
    quietTimer.current = setTimeout(() => setQuiet(true), 2000);
  };
  useEffect(() => { wake(); return () => clearTimeout(quietTimer.current); }, []);
  // the key starts tucked away on phones, where it would cover most of the map; a choice made before is kept
  const [key, setKey] = useState(() => {
    let saved = null;
    try { saved = localStorage.getItem('rz-legend'); } catch { /* private mode */ }
    return saved ? saved === 'open' : !window.matchMedia('(max-width: 600px)').matches;
  });
  const showKey = (v) => { setKey(v); try { localStorage.setItem('rz-legend', v ? 'open' : 'closed'); } catch { /* private mode */ } };
  useEffect(() => {
    map.current?.resize();
    const coop = map.current?.cooperativeGestures;
    if (coop) full || !stacked.matches ? coop.disable() : coop.enable(); // full screen: the map owns every gesture
    if (!full) return;
    const esc = (e) => e.key === 'Escape' && setFull(false);
    window.addEventListener('keydown', esc);
    document.body.style.overflow = 'hidden'; // the page behind must not scroll under the full-screen map
    return () => { window.removeEventListener('keydown', esc); document.body.style.overflow = ''; };
  }, [full]);
  const rings = zones ? legend(zones.coverage) : [];
  const last = rings.length - 1;
  const ids = zones?.corridors?.map((c) => c.id) ?? [];

  useEffect(() => {
    const m = new maplibregl.Map({ container: box.current, style: STYLE[theme], center: [-121.97, 37.32], zoom: 8,
      attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false,
      fadeDuration: 120, // labels that swap places while moving fade quickly instead of blinking
      // stacked layout: the page scrolls past the map, so one finger scrolls the page and two move the map
      cooperativeGestures: stacked.matches });
    m.touchZoomRotate.disableRotation();
    m.on('style.load', () => setReady((n) => n + 1)); // re-add our layers after every style swap
    // map credits start as the small (i) button, not a wide strip over the map key; tapping it still shows them
    m.once('load', () => box.current?.querySelector('.maplibregl-compact-show')?.classList.remove('maplibregl-compact-show'));
    // click a zone: what it is, in words
    const popup = new maplibregl.Popup({ closeButton: false, maxWidth: '260px', offset: 6 });
    m.on('click', 'zones-fill', (e) => {
      const p = e.features?.[0]?.properties;
      if (p && latest.current) popup.setLngLat(e.lngLat).setDOMContent(zoneCard(p, latest.current.coverage)).addTo(m);
    });
    m.on('mouseenter', 'zones-fill', () => { m.getCanvas().style.cursor = 'pointer'; });
    m.on('mouseleave', 'zones-fill', () => { m.getCanvas().style.cursor = ''; });
    map.current = m;
    return () => m.remove();
  }, []);

  useEffect(() => {
    if (shown.current === theme) return;
    shown.current = theme;
    map.current.setStyle(STYLE[theme], { diff: false });
  }, [theme]);

  useEffect(() => {
    const m = map.current;
    if (!ready || !zones || !m.getStyle()) return; // mid style swap: 'style.load' bumps `ready` and we run again
    const data = { ...zones, features: zones.features.map((f) => ({ ...f, properties: { ...f.properties, colour: zoneColour(f.properties, colourBy, ids, last) } })) };
    if (m.getSource('zones')) {
      m.getSource('zones').setData(data);
      m.getSource('zone-labels').setData(zones.labels);
    } else {
      const firstLabel = m.getStyle().layers.find((l) => l.type === 'symbol')?.id;
      m.addSource('zones', { type: 'geojson', data });
      m.addLayer({ id: 'zones-fill', type: 'fill', source: 'zones', paint: { 'fill-color': ['get', 'colour'] } }, firstLabel);
      // a crisp border between neighbouring zones, so each zone reads as its own area
      m.addLayer({ id: 'zones-line', type: 'line', source: 'zones', layout: { 'line-join': 'round' }, paint: {
        'line-color': scheme === 'dark' ? '#000000' : '#FFFFFF',
        'line-width': ['interpolate', ['linear'], ['zoom'], 7, 1.2, 10, 2, 13, 3],
      } }, firstLabel);
      m.addLayer({ id: 'zone-pick', type: 'line', source: 'zones', paint: { 'line-color': scheme === 'dark' ? '#FFFFFF' : '#000000', 'line-width': 2.5, 'line-dasharray': [2, 2] }, filter: ['==', ['get', 'zone'], ''] });
      // zone codes (1B, 1BD…) on each zone; bigger zones win when labels would overlap
      m.addSource('zone-labels', { type: 'geojson', data: zones.labels });
      m.addLayer({ id: 'zone-labels', type: 'symbol', source: 'zone-labels', layout: {
        'text-field': ['get', 'zone'], 'text-font': ['Noto Sans Bold'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 7, 12, 11, 16], 'symbol-sort-key': ['-', ['get', 'cells']],
        // if the middle is taken, try just above/below/beside it before hiding the label (as Mapbox-based maps do)
        'text-variable-anchor': ['center', 'top', 'bottom', 'left', 'right'], 'text-radial-offset': 0.7,
        'text-padding': 2,
      }, paint: {
        'text-color': scheme === 'dark' ? '#FFFFFF' : '#000000',
        'text-halo-color': scheme === 'dark' ? 'rgba(0,0,0,0.85)' : 'rgba(255,255,255,0.9)', 'text-halo-width': 1.6,
      } });
    }
  }, [ready, zones, last, scheme, colourBy]);

  useEffect(() => {
    if (zones) map.current.fitBounds(bounds(zones), { padding: pad(40), duration: 0 });
  }, [zones]);

  useEffect(() => {
    const m = map.current;
    if (!ready || !m.getLayer('zones-fill')) return;
    // the chosen zone always keeps the full colour strength; only the others fade
    const a = opacity / 100;
    const on = ['==', ['get', 'zone'], focus || ''];
    m.setPaintProperty('zones-fill', 'fill-opacity', focus ? ['case', on, a, a * 0.2] : a);
    m.setPaintProperty('zones-line', 'line-opacity', focus ? ['case', on, 1, 0.3] : 0.95);
    m.setFilter('zone-pick', ['==', ['get', 'zone'], highlight || focus || '']);
    m.setPaintProperty('zone-labels', 'text-opacity', focus ? ['case', on, 1, 0.25] : 1);
  }, [ready, zones, focus, opacity, highlight]);

  useEffect(() => {
    if (!zones) return;
    const one = focus ? { ...zones, base: null, features: zones.features.filter((f) => f.properties.zone === focus) } : null;
    map.current.fitBounds(bounds(one?.features.length ? one : zones), { padding: pad(60), maxZoom: 12, duration: 500 });
  }, [focus]);

  useEffect(() => {
    const place = (key, lngLat, cls, label, tag) => {
      marks.current[key]?.remove();
      delete marks.current[key];
      if (!lngLat) return;
      const el = document.createElement('div');
      el.className = cls;
      el.setAttribute('role', 'img');
      el.setAttribute('aria-label', tag ? `${label}: ${tag}` : label);
      if (tag) { const t = document.createElement('span'); t.className = 'pin-tag'; t.textContent = tag; el.append(t); } // map callout, as Uber's "0.5 miles"
      marks.current[key] = new maplibregl.Marker({ element: el }).setLngLat(lngLat).addTo(map.current);
    };
    place('dealer', zones?.base, 'pin-dealer', `${name} dealership`);
    place('customer', point, 'pin-customer', 'Customer address', pointTag);
    if (point && zones) map.current.fitBounds(bounds({ base: zones.base }, [point]), { padding: pad(90), maxZoom: 13, duration: 600 });
  }, [zones, point, pointTag, name]);

  const recenter = () => zones && map.current.fitBounds(bounds(zones), { padding: pad(40), duration: 500 });
  // ring-by-ring swatch for one corridor: the same hue getting darker further out
  const ramp = (id) => `linear-gradient(90deg, ${rings.slice(1).map((r) => shade(corridorColour(id, ids), r.band)).join(', ') || corridorColour(id, ids)})`;

  return (
    <section className={`map${full ? ' full' : ''}${quiet ? ' quiet' : ''}`} aria-label={`Zone map for ${name}`}
      onPointerDown={wake} onPointerMove={wake} onWheel={wake} onFocus={wake} onKeyDown={wake}>
      <div ref={box} className="map-canvas" />
      {!zones && (
        <div className="map-loading" role="status"><span className="spinner" aria-hidden="true" /><span>Loading zones…</span></div>
      )}
      {zones && busy && (
        <div className="map-busy" role="status"><span className="spinner" aria-hidden="true" /><span>{busy}</span></div>
      )}
      <div className="map-pill"><span className="dot" /><strong className="ell">{name}</strong></div>
      <div className="map-tools">
        <div className="zoom">
          <button type="button" aria-label="Zoom in" onClick={() => map.current.zoomIn()}><Icon name="plus" /></button>
          <hr />
          <button type="button" aria-label="Zoom out" onClick={() => map.current.zoomOut()}><Icon name="minus" /></button>
        </div>
        <button type="button" aria-label={full ? 'Exit full screen' : 'Full screen map'} aria-pressed={full} onClick={() => setFull(!full)}><Icon name={full ? 'shrink' : 'expand'} /></button>
        <button type="button" aria-label="Show all zones" onClick={recenter}><Icon name="locate" /></button>
      </div>
      {zones && !key && (
        <button type="button" className="legend-open" aria-expanded="false" onClick={() => showKey(true)}><Icon name="chevron" size={16} width={2.2} />Map key</button>
      )}
      {zones && key && (
        <div className="legend">
          <div className="legend-head">
            <div className="seg" role="group" aria-label="Colour the map by">
              <button type="button" aria-pressed={colourBy === 'zones'} onClick={() => onColourBy('zones')}>Highways</button>
              <button type="button" aria-pressed={colourBy === 'distance'} onClick={() => onColourBy('distance')}>Distance</button>
            </div>
            <span className="legend-tools">
              <button type="button" className="link" onClick={onHelp}>How colours work</button>
              <button type="button" className="legend-hide" aria-label="Hide map key" aria-expanded="true" onClick={() => showKey(false)}><Icon name="chevron" size={16} width={2.2} /></button>
            </span>
          </div>
          {colourBy === 'zones' ? (
            <>
              <ul className="corridors">
                {zones.corridors.filter((c) => c.id !== 'HUB').map((c) => (
                  <li key={c.id}>
                    <i style={{ background: c.id === 'L' ? corridorColour('L', ids) : ramp(c.id) }} />
                    <b>{c.id}</b><span className="ell">{c.road}</span>
                  </li>
                ))}
                {ids.includes('HUB') && <li><i style={{ background: corridorColour('HUB', ids) }} /><b>0</b><span>Hub · {zones.coverage.hub_miles} mi</span></li>}
              </ul>
              <p className="legend-note">Darker = further out. 2B is ring 2 on highway B. Click a zone for details.</p>
            </>
          ) : (
            <>
              <strong className="legend-title">Road miles from dealer</strong>
              <div className="legend-steps">
                {rings.map((l) => (
                  <div key={l.band}><i style={{ background: l.colour }} /><b>{l.name}</b><span>{l.range}</span></div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
