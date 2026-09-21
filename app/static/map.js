(() => {
  'use strict';
  const element = document.getElementById('lake-map');
  if (!element) return;
  let map;
  // Windy remains usable if Leaflet or its CDN is unavailable.
  document.querySelectorAll('[data-map-tab]').forEach(button => button.addEventListener('click', () => {
    const windy = document.getElementById('windy-map');
    if (!windy) return;
    const showWindy = button.dataset.mapTab === 'windy';
    document.querySelectorAll('[data-map-tab]').forEach(b => { b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', String(b === button)); });
    element.hidden = showWindy; windy.hidden = !showWindy;
    if (showWindy && !windy.firstElementChild) {
      const frame = document.createElement('iframe'); frame.src = windy.dataset.src; frame.title = 'Windy wind map with independent forecast time controls';
      windy.appendChild(frame);
    }
    if (!showWindy && map) map.invalidateSize();
  }));
  if (!window.L) return;
  const parse = id => { try { return JSON.parse(document.getElementById(id)?.textContent || '[]'); } catch { return []; } };
  const spots = parse('map-spots'), stations = parse('station-data');
  element.replaceChildren();
  map = L.map(element, {scrollWheelZoom: false, zoomControl: true});
  const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
  tiles.on('tileerror', () => { element.setAttribute('aria-label', 'Map tiles unavailable. Spot and station links are available in the page.'); });
  const spotLayer = L.layerGroup().addTo(map), buoyLayer = L.layerGroup().addTo(map);
  const points = [];
  const cardinal = value => value == null ? '—' : 'N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW'.split(' ')[Math.floor((value + 11.25) / 22.5) % 16];
  function popup(name, text, url, label) {
    const root = document.createElement('div'); root.className = 'map-popup';
    const heading = document.createElement('h3'); heading.textContent = name;
    const paragraph = document.createElement('p'); paragraph.textContent = text;
    const link = document.createElement('a'); link.href = url; link.textContent = label;
    root.append(heading, paragraph, link); return root;
  }
  const h = new URLSearchParams(location.search).get('h') || '0';
  for (const spot of spots) {
    const marker = document.createElement('span'); marker.textContent = spot.score == null ? '—' : String(spot.score);
    const icon = L.divIcon({className: 'map-marker' + (spot.score == null ? ' unrated' : ''), html: marker, iconSize: [30, 30], iconAnchor: [15, 15]});
    const details = spot.wind == null ? 'Wind forecast unavailable.' : `${Math.round(spot.wind)} kt from ${cardinal(spot.direction)} · wind setup ${spot.score ?? 'unavailable'}${spot.score == null ? '' : '/100'}`;
    L.marker([spot.lat, spot.lng], {icon, title: `${spot.name} · ${details}`}).bindPopup(popup(spot.name, details, `/spots/${encodeURIComponent(spot.id)}?h=${encodeURIComponent(h)}`, 'View spot & forecast ↗')).addTo(spotLayer);
    points.push([spot.lat, spot.lng]);
  }
  for (const station of stations) {
    const marker = document.createElement('span'); marker.textContent = '◇';
    const icon = L.divIcon({className: 'buoy-marker', html: marker, iconSize: [23, 23], iconAnchor: [12, 12]});
    const readings = [];
    const wind = station.measurements.wind_kts, wave = station.measurements.wave_height_m, water = station.measurements.water_temp_c;
    const observed = reading => `${reading.status} · ${new Date(reading.time).toLocaleString()}`;
    if (wave) readings.push(`Waves ${(wave.value * 3.28084).toFixed(1)} ft · ${observed(wave)}`);
    if (wind) readings.push(`Wind ${Math.round(wind.value)} kt · ${observed(wind)}`);
    if (!wave && !wind && water) readings.push(`Water ${Math.round(water.value * 1.8 + 32)} °F · ${observed(water)}`);
    const details = readings.length ? readings.join(' / ') : 'No recent readings. Station is still shown for reference.';
    // Each direction retains its own timestamp in the station card.
    L.marker([station.lat, station.lng], {icon, title: `${station.name} (${station.id})`}).bindPopup(popup(station.name, details, `/buoys#station-${station.id}`, 'View observations ↗')).addTo(buoyLayer);
  }
  const allPoints = [...points, ...stations.map(s => [s.lat, s.lng])];
  const fit = coords => { if (coords.length) map.fitBounds(coords, {padding: [35, 35], maxZoom: 10}); else map.setView([44, -87], 7); };
  fit(points.length ? points : allPoints);
  const overlays = {'Buoys & stations': buoyLayer};
  if (spots.length) overlays['Surf spots'] = spotLayer;
  L.control.layers(null, overlays, {collapsed: true}).addTo(map);
  if (points.length) {
    const control = L.control({position: 'bottomleft'});
    control.onAdd = () => {
      const button = L.DomUtil.create('button', 'map-extent-button'); button.type = 'button'; button.textContent = 'Show offshore buoys';
      let offshore = false;
      L.DomEvent.disableClickPropagation(button);
      button.addEventListener('click', () => { offshore = !offshore; fit(offshore ? allPoints : points); button.textContent = offshore ? 'Focus on our spots' : 'Show offshore buoys'; });
      return button;
    };
    control.addTo(map);
  }
})();
