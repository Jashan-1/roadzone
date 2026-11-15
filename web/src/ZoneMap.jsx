import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import { bandColour, legend } from './zone.js';
import { Icon } from './Icon.jsx';

// OpenFreeMap: free vector tiles, no key, commercial use allowed
const STYLE = { light: 'https://tiles.openfreemap.org/styles/positron', dark: 'https://tiles.openfreemap.org/styles/dark' };
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

export default function ZoneMap({ zones, name, point, highlight, focus, opacity, theme }) {
  const box = useRef(null);
  const map = useRef(null);
  const marks = useRef({});
  const shown = useRef(theme);
  const scheme = theme;
  const [ready, setReady] = useState(0);
  const last = zones ? legend(zones.coverage).length - 1 : 0;

  useEffect(() => {
    const m = new maplibregl.Map({ container: box.current, style: STYLE[theme], center: [-121.97, 37.32], zoom: 8,
      attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false });
    m.touchZoomRotate.disableRotation();
    m.on('style.load', () => setReady((n) => n + 1)); // re-add our layers after every style swap
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
    const data = { ...zones, features: zones.features.map((f) => ({ ...f, properties: { ...f.properties, colour: bandColour(f.properties.band, last) } })) };
    if (m.getSource('zones')) m.getSource('zones').setData(data);
    else {
      const firstLabel = m.getStyle().layers.find((l) => l.type === 'symbol')?.id;
      m.addSource('zones', { type: 'geojson', data });
      m.addLayer({ id: 'zones-fill', type: 'fill', source: 'zones', paint: { 'fill-color': ['get', 'colour'] } }, firstLabel);
      m.addLayer({ id: 'zones-line', type: 'line', source: 'zones', paint: { 'line-color': ['get', 'colour'], 'line-width': 0.6 } }, firstLabel);
      m.addLayer({ id: 'zone-pick', type: 'line', source: 'zones', paint: { 'line-color': scheme === 'dark' ? '#FFFFFF' : '#000000', 'line-width': 2.5, 'line-dasharray': [2, 2] }, filter: ['==', ['get', 'zone'], ''] });
    }
  }, [ready, zones, last, scheme]);

  useEffect(() => {
    if (zones) map.current.fitBounds(bounds(zones), { padding: 40, duration: 0 });
  }, [zones]);

  useEffect(() => {
    const m = map.current;
    if (!ready || !m.getLayer('zones-fill')) return;
    // the chosen zone always keeps the full colour strength; only the others fade
    const a = opacity / 100;
    const on = ['==', ['get', 'zone'], focus || ''];
    m.setPaintProperty('zones-fill', 'fill-opacity', focus ? ['case', on, a, a * 0.2] : a);
    m.setPaintProperty('zones-line', 'line-opacity', focus ? ['case', on, 1, 0.15] : 0.5);
    m.setFilter('zone-pick', ['==', ['get', 'zone'], highlight || focus || '']);
  }, [ready, zones, focus, opacity, highlight]);

  useEffect(() => {
    if (!zones) return;
    const one = focus ? { ...zones, base: null, features: zones.features.filter((f) => f.properties.zone === focus) } : null;
    map.current.fitBounds(bounds(one?.features.length ? one : zones), { padding: 60, maxZoom: 12, duration: 500 });
  }, [focus]);

  useEffect(() => {
    const place = (key, lngLat, cls, label) => {
      marks.current[key]?.remove();
      delete marks.current[key];
      if (!lngLat) return;
      const el = document.createElement('div');
      el.className = cls;
      el.setAttribute('role', 'img');
      el.setAttribute('aria-label', label);
      marks.current[key] = new maplibregl.Marker({ element: el }).setLngLat(lngLat).addTo(map.current);
    };
    place('dealer', zones?.base, 'pin-dealer', `${name} dealership`);
    place('customer', point, 'pin-customer', 'Customer address');
    if (point && zones) map.current.fitBounds(bounds({ base: zones.base }, [point]), { padding: 90, maxZoom: 13, duration: 600 });
  }, [zones, point, name]);

  const recenter = () => zones && map.current.fitBounds(bounds(zones), { padding: 40, duration: 500 });

  return (
    <section className="map" aria-label={`Zone map for ${name}`}>
      <div ref={box} className="map-canvas" />
      {!zones && <div className="map-empty">Loading zones…</div>}
      <div className="map-pill"><span className="dot" /><strong className="ell">{name}</strong></div>
      <div className="map-tools">
        <div className="zoom">
          <button type="button" aria-label="Zoom in" onClick={() => map.current.zoomIn()}><Icon name="plus" /></button>
          <hr />
          <button type="button" aria-label="Zoom out" onClick={() => map.current.zoomOut()}><Icon name="minus" /></button>
        </div>
        <button type="button" aria-label="Show all zones" onClick={recenter}><Icon name="locate" /></button>
      </div>
      {zones && (
        <div className="legend">
          <strong>Road miles from dealer</strong>
          <div className="legend-steps">
            {legend(zones.coverage).map((l) => (
              <div key={l.band}><i style={{ background: l.colour }} /><b>{l.name}</b><span>{l.range}</span></div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
