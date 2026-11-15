import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import { bandColour, legend } from './zone.js';
import { Icon } from './Icon.jsx';

// OpenFreeMap: free vector tiles, no key, commercial use allowed
const STYLE = { light: 'https://tiles.openfreemap.org/styles/positron', dark: 'https://tiles.openfreemap.org/styles/dark' };
const dark = window.matchMedia('(prefers-color-scheme: dark)');

function bounds(fc, extra = []) {
  const b = new maplibregl.LngLatBounds();
  for (const f of fc?.features ?? []) {
    const g = f.geometry;
    const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
    for (const poly of polys) for (const [x, y] of poly[0]) b.extend([x, y]); // outer rings are enough
  }
  if (fc?.base) b.extend(fc.base);
  for (const p of extra) b.extend(p);
  return b;
}

export default function ZoneMap({ zones, name, point, highlight, focus, opacity }) {
  const box = useRef(null);
  const map = useRef(null);
  const marks = useRef({});
  const [scheme, setScheme] = useState(dark.matches ? 'dark' : 'light');
  const [ready, setReady] = useState(0);
  const last = zones ? legend(zones.coverage).length - 1 : 0;

  useEffect(() => {
    const m = new maplibregl.Map({ container: box.current, style: STYLE[scheme], center: [-121.97, 37.32], zoom: 8,
      attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false });
    m.touchZoomRotate.disableRotation();
    m.on('style.load', () => setReady((n) => n + 1)); // re-add our layers after every style swap
    map.current = m;
    const flip = (e) => {
      const s = e.matches ? 'dark' : 'light';
      setScheme(s);
      m.setStyle(STYLE[s], { diff: false });
    };
    dark.addEventListener('change', flip);
    return () => { dark.removeEventListener('change', flip); m.remove(); };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!ready || !zones) return;
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
    const a = opacity / 100;
    m.setPaintProperty('zones-fill', 'fill-opacity', focus ? ['case', ['==', ['get', 'zone'], focus], a, a * 0.15] : a);
    m.setPaintProperty('zones-line', 'line-opacity', focus ? ['case', ['==', ['get', 'zone'], focus], 0.9, 0.1] : 0.5);
    m.setFilter('zone-pick', ['==', ['get', 'zone'], highlight || '']);
  }, [ready, zones, focus, opacity, highlight]);

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
