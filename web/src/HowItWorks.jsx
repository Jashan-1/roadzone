import { useEffect, useRef } from 'react';
import { Icon } from './Icon.jsx';
import { legend } from './zone.js';

/** Plain-language explainer: how distances, colours and zone codes are made. Numbers come from the run on screen. */
export default function HowItWorks({ open, onClose, loc }) {
  const dlg = useRef(null);
  useEffect(() => {
    const d = dlg.current;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  const s = loc ?? { limit_miles: 50, hub_miles: 5, band_step_miles: 10, min_corridor_cells: 30, highways: [] };
  const rings = legend(s);
  const hw = { I: 'Interstates', US: 'US highways', CA: 'state highways' };
  const ticked = s.highways?.length ? s.highways.map((h) => hw[h]).join(', ') : 'the highway types picked for this location';

  return (
    <dialog ref={dlg} onClose={onClose} aria-labelledby="how-title" className="how">
      <div className="dlg-head">
        <div style={{ flexGrow: 1 }}>
          <h2 id="how-title">How RoadZone works</h2>
          <p>{loc ? `Numbers below are for ${loc.name}.` : 'How zones, colours and checks are made.'}</p>
        </div>
        <button type="button" className="round" aria-label="Close" onClick={onClose}><Icon name="close" size={16} /></button>
      </div>
      <div className="dlg-body prose">
        <section>
          <h3>Distances are road miles</h3>
          <p>The map is split into small hexagon tiles, each about 0.7 km² (0.3 sq mi). For every tile, RoadZone drives from the dealership to the tile and back on the real road network, using OpenStreetMap roads, and keeps the longer of the two trips. Two places the same distance away in a straight line can land in different zones if one is across a ridge or a bay.</p>
        </section>

        <section>
          <h3>What the colours mean</h3>
          <p>The switch on the map legend picks one of two views.</p>
          <ul>
            <li><strong>Highways</strong> (the default): each highway corridor has its own colour, and it gets darker for every ring further out. So 1B, 2B and 3B are shades of one colour, and you can see which zones follow the same highway. The Hub is dark grey and local roads are tan.</li>
            <li><strong>Distance</strong>: colour shows only how far a place is by road, green near the dealership to red at the edge.</li>
          </ul>
          <p>Everything within {s.hub_miles} road miles is the Hub (zone 0). After that a new ring starts every {s.band_step_miles} miles, out to {s.limit_miles} miles. Places further than that are outside the service area and have no colour.</p>
          <div className="how-scale" role="img" aria-label={rings.map((r) => `${r.name}: ${r.range}`).join(', ')}>
            {rings.map((r) => (
              <div key={r.band}><i style={{ background: r.colour }} /><b>{r.name}</b><span>{r.range}</span></div>
            ))}
          </div>
          <p>Click any zone on the map to see its ring, distance and highway. Colour strength in Map settings only changes how see-through the colours are, so streets and town names show underneath.</p>
        </section>

        <section>
          <h3>How zone codes are made</h3>
          <p>A code like <strong>2AB</strong> has two parts. The number is the ring: 2 means ring 2. The letters are the highway the route mostly uses to get there. Each of the {ticked} gets its own letter.</p>
          <ul>
            <li>A second letter is a branch: <strong>2AB</strong> is reached by going through <strong>2A</strong>.</li>
            <li><strong>L</strong> means local roads, off the lettered highways.</li>
            <li>Zones smaller than {s.min_corridor_cells} map tiles are joined into the zone next to them, so the map isn’t full of tiny zones.</li>
          </ul>
        </section>

        <section>
          <h3>Checking an address</h3>
          <p>The address is placed on the map and routed the same way as the tiles. The answer is one of three:</p>
          <ul>
            <li><strong>In service area</strong>, with its zone and road miles.</li>
            <li><strong>Needs a double-check</strong> when the route isn’t certain. For example, the last stretch is a track or unnamed road, the address is far from any road, or it sits on a highway this map has no letter for. Confirm these with dispatch.</li>
            <li><strong>Outside service area</strong> when it is more than {s.limit_miles} road miles away.</li>
          </ul>
          <p>Coordinates stay on this server. A typed address is first looked up on OpenStreetMap, an outside website.</p>
        </section>

        <section>
          <h3>What it doesn’t know</h3>
          <ul>
            <li>Traffic. Miles are what count; drive times assume empty roads.</li>
            <li>Changes after the map data was downloaded. Map data covers California only.</li>
          </ul>
        </section>
      </div>
    </dialog>
  );
}
