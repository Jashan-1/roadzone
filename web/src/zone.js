// Pure helpers that turn a /zone answer and a run's coverage into what the advisor sees and says.

export const HIGHWAYS = [['I', 'Interstate (I)'], ['US', 'US routes'], ['CA', 'State routes (CA)']];

export const BAND_COLOURS = ['#2E9A57', '#8CC96E', '#E6D36A', '#F0A64C', '#E4704A', '#C8403A'];

const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
  'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty'];

// one clearly different hue per highway corridor; Hub and local roads keep the neutral colours Streamlit uses
const CORRIDOR_COLOURS = ['#3B7DD8', '#E8833A', '#3FA34D', '#D9445A', '#8E5CC9', '#1FA9A3', '#C9A227', '#D45FA8',
  '#6B8E23', '#8C6D4F', '#4BA3E3', '#B5533C'];
const HUB_COLOUR = '#52525B';
const LOCAL_COLOUR = '#C2A878';

/** Colour for a corridor id, by its place in the run's sorted corridor list (stable for a run). */
export function corridorColour(id, ids) {
  if (id === 'HUB') return HUB_COLOUR;
  if (id === 'L') return LOCAL_COLOUR;
  const named = ids.filter((x) => x !== 'HUB' && x !== 'L');
  const i = Math.max(0, named.indexOf(id));
  if (i < CORRIDOR_COLOURS.length) return CORRIDOR_COLOURS[i];
  return `hsl(${Math.round((i * 137.508) % 360)} 55% ${i % 2 ? 42 : 56}%)`; // golden-angle steps past the palette
}

/** Same hue, darker for each ring further out (ring 1 unchanged): 1A, 2A, 3A read as one highway. */
export function shade(hex, band) {
  if (!hex.startsWith('#') || !band || band <= 1) return hex;
  const f = Math.max(0.45, 1 - 0.16 * (band - 1));
  const c = [1, 3, 5].map((i) => Math.round(parseInt(hex.slice(i, i + 2), 16) * f));
  return `#${c.map((x) => x.toString(16).padStart(2, '0')).join('')}`;
}

/** Fill colour for one zone: by highway (default) or by distance ring. */
export function zoneColour(p, mode, ids, lastBand) {
  if (mode === 'distance') return bandColour(p.band, lastBand);
  const base = corridorColour(p.corridor, ids);
  return p.corridor === 'HUB' ? base : shade(base, p.band);
}

/** Same zone settings mix (highway order ignored), as app.py's run_key. */
export function sameSettings(a, b) {
  const hw = (x) => [...(x.highways || [])].sort().join(',');
  return ['limit_miles', 'hub_miles', 'band_step_miles', 'min_corridor_cells'].every((k) => Number(a[k]) === Number(b[k]))
    && hw(a) === hw(b);
}

/** [0, hub, hub+step, ..., limit]: the same edges zonegen.classify.band_edges uses. */
export function bandEdges({ hub_miles: hub, band_step_miles: step, limit_miles: limit }) {
  const edges = [0];
  for (let k = 0; hub + k * step < limit; k++) edges.push(hub + k * step);
  return [...edges, limit];
}

/** Green at the Hub to red at the last band, spread over the design's six stops. */
export function bandColour(band, last) {
  if (band == null) return BAND_COLOURS[BAND_COLOURS.length - 1];
  const i = last > 0 ? Math.round((band / last) * (BAND_COLOURS.length - 1)) : 0;
  return BAND_COLOURS[Math.min(BAND_COLOURS.length - 1, Math.max(0, i))];
}

export function legend(coverage) {
  const e = bandEdges(coverage);
  const last = e.length - 2;
  return e.slice(0, -1).map((a, i) => ({
    band: i, name: i === 0 ? 'Hub' : String(i), range: `${a}–${e[i + 1]}${i === 0 ? ' mi' : ''}`,
    colour: bandColour(i, last),
  }));
}

/** 'in' | 'review' | 'out'. Unsure answers are never shown as a confident yes. */
export function verdict(r) {
  if (r.status === 'outside_coverage') return 'out';
  if (r.zone && !r.zone.includes('?') && !r.review) return 'in';
  return 'review';
}

/** '2AB' -> 'two A B'; the Hub is '0'. */
export function spoken(code) {
  const m = /^(\d+)(.*)$/.exec(code || '');
  if (!m) return code || '';
  const n = Number(m[1]);
  const num = n < WORDS.length ? WORDS[n] : m[1];
  const letters = m[2].split('').map((c) => (c === '?' ? 'unknown highway' : c));
  return [n === 0 && !letters.length ? 'zero, the Hub' : num, ...letters].join(' ');
}

/** '2AB' is reached through '2A'. Single-letter zones sit on the highway itself. */
export function viaZone(code) {
  const m = /^(\d+)([A-Z]{2,})$/.exec(code || '');
  return m ? m[1] + m[2].slice(0, -1) : null;
}

export function bandRange(band, coverage) {
  if (band == null) return null;
  const e = bandEdges(coverage);
  return band < e.length - 1 ? `${e[band]}–${e[band + 1]}` : null;
}

/** First three parts of a long geocoder label: '1 Main St, Cupertino, CA'. */
export function shortPlace(label) {
  return (label || '').split(',').map((s) => s.trim()).filter(Boolean).slice(0, 3).join(', ');
}

export function reviewNote(r) {
  const why = r.reasons && r.reasons !== '-' ? ` Flagged: ${r.reasons.replaceAll('_', ' ').replaceAll(',', ', ')}.` : '';
  return (r.zone
    ? 'The road route to this address isn’t certain. Confirm access with dispatch before booking.'
    : 'We couldn’t find a clear road route to this address. Check it with dispatch before booking.') + why;
}

export function script(v, r, limit) {
  if (v === 'in') return `Good news, we cover your area. Your service zone is ${r.zone}, about ${r.miles} road miles from us.`;
  if (v === 'review') return 'Let me confirm the last stretch of road with our dispatch team, and I’ll call you right back.';
  return r.miles
    ? `I’m sorry, you’re about ${r.miles} road miles away, and our vans go up to ${limit}.`
    : 'I’m sorry, you’re outside the area our vans cover.';
}

export function bookingNote(v, r) {
  const zone = r.zone ? `Zone ${r.zone}${v === 'review' ? ' (needs review)' : ''}` : 'Outside service area';
  return [zone, r.miles != null ? `${r.miles} road mi` : null, shortPlace(r.label)].filter(Boolean).join(' · ');
}
