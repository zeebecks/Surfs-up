/* Independent enhancements: external maps and cameras cannot break the core UI. */
(() => {
  'use strict';
  const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Device storage is optional. */ } };
  let favorites = new Set((Array.isArray(read('lake-surf:favorites', [])) ? read('lake-surf:favorites', []) : []).filter(v => typeof v === 'string'));
  let filter = 'all';
  function updateFavorites() {
    document.querySelectorAll('[data-favorite]').forEach(button => {
      const saved = favorites.has(button.dataset.favorite);
      button.setAttribute('aria-pressed', String(saved));
      button.textContent = saved ? '★' : '☆';
    });
    let visible = 0;
    document.querySelectorAll('.spot-card').forEach(card => {
      card.hidden = filter === 'favorites' && !favorites.has(card.dataset.spotId);
      if (!card.hidden) visible++;
    });
    const empty = document.getElementById('favorites-empty');
    if (empty) empty.hidden = visible !== 0;
  }
  document.querySelectorAll('[data-favorite]').forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.favorite;
    if (favorites.has(id)) favorites.delete(id); else favorites.add(id);
    write('lake-surf:favorites', [...favorites]);
    updateFavorites();
  }));
  document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    filter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(b => {
      b.classList.toggle('active', b === button);
      b.setAttribute('aria-pressed', String(b === button));
    });
    updateFavorites();
  }));
  updateFavorites();
  document.getElementById('spot-sort')?.addEventListener('change', event => {
    const key = event.target.value;
    const cards = [...document.querySelectorAll('.spot-card')];
    cards.sort((a, b) => key === 'coast' ? Number(a.dataset.coast) - Number(b.dataset.coast)
      : Number(b.dataset[key + 'Score']) - Number(a.dataset[key + 'Score']) || Number(a.dataset.coast) - Number(b.dataset.coast));
    cards.forEach(card => card.parentElement.appendChild(card));
  });

  // Tokens arrive in a URL fragment, never a server-visible query parameter.
  const fragment = new URLSearchParams(location.hash.slice(1));
  let tokens = read('lake-surf:checkins', {});
  if (!tokens || typeof tokens !== 'object' || Array.isArray(tokens)) tokens = {};
  const ident = fragment.get('checkin_id'), token = fragment.get('token');
  if (ident && /^\d+$/.test(ident) && token) {
    tokens[ident] = token;
    write('lake-surf:checkins', tokens);
    history.replaceState(null, '', location.pathname + location.search);
  }
  document.querySelectorAll('[data-checkin-id]').forEach(form => {
    const value = tokens[form.dataset.checkinId];
    if (typeof value === 'string') {
      form.elements.token.value = value;
      form.hidden = false;
    }
  });
  const arrival = document.getElementById('arrival'), departure = document.getElementById('departure');
  function validateTimes() { if (arrival && departure) departure.setCustomValidity(arrival.value && departure.value && departure.value <= arrival.value ? 'Choose a departure after your arrival, on the same day.' : ''); }
  arrival?.addEventListener('input', validateTimes);
  departure?.addEventListener('input', validateTimes);

  document.querySelectorAll('[data-camera-src]').forEach(panel => {
    const original = [...panel.childNodes].map(node => node.cloneNode(true));
    let timeout;
    function reset() {
      clearTimeout(timeout);
      panel.replaceChildren(...original.map(node => node.cloneNode(true)));
      panel.classList.remove('camera-loaded');
      wire();
    }
    function wire() {
      panel.querySelector('.camera-play')?.addEventListener('click', () => {
        const iframe = panel.dataset.cameraKind === 'iframe';
        const media = document.createElement(iframe ? 'iframe' : 'img');
        media.className = 'camera-media';
        if (iframe) { media.title = panel.dataset.cameraTitle; media.allowFullscreen = true; media.allow = 'autoplay; encrypted-media; picture-in-picture'; }
        else media.alt = panel.dataset.cameraTitle + ' live camera';
        const stop = document.createElement('button');
        stop.type = 'button'; stop.className = 'camera-stop'; stop.textContent = 'Close camera';
        stop.addEventListener('click', reset);
        const unavailable = () => {
          clearTimeout(timeout);
          media.remove();
          const message = document.createElement('p');
          message.textContent = 'This camera isn’t responding. Try the original camera link below.';
          panel.prepend(message);
          stop.textContent = 'Try again';
        };
        media.addEventListener('error', unavailable, {once: true});
        media.addEventListener('load', () => clearTimeout(timeout), {once: true});
        media.src = panel.dataset.cameraSrc;
        panel.replaceChildren(media, stop);
        panel.classList.add('camera-loaded');
        // MJPEG image load may not fire until the stream ends, so do not time out a
        // healthy endless stream in the browser. The server bounds stalled reads.
      });
    }
    wire();
  });

  const stationData = document.getElementById('station-data');
  let stations = [];
  try { stations = JSON.parse(stationData?.textContent || '[]'); } catch { /* Leave the readings table usable. */ }
  function drawTrend(canvas) {
    const station = stations.find(s => s.id === canvas.dataset.station);
    const rows = [...(station?.history || [])].reverse();
    const usable = rows.filter(row => Number.isFinite(row.wind_kts));
    if (usable.length < 2) { canvas.hidden = true; return; }
    const width = canvas.clientWidth, height = 75, ratio = window.devicePixelRatio || 1;
    if (!width) return;
    canvas.width = width * ratio; canvas.height = height * ratio;
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    ctx.scale(ratio, ratio);
    const max = Math.max(10, ...usable.map(row => row.wind_kts)) * 1.2;
    const first = Date.parse(rows[0].time), last = Date.parse(rows[rows.length - 1].time);
    if (last === first) return;
    const x = row => 6 + (Date.parse(row.time) - first) / (last - first) * (width - 40);
    const y = row => height - 19 - row.wind_kts / max * (height - 30);
    ctx.strokeStyle = '#314950'; ctx.lineWidth = 1;
    for (const f of [0, .5, 1]) { const yy = height - 19 - f * (height - 30); ctx.beginPath(); ctx.moveTo(5, yy); ctx.lineTo(width - 29, yy); ctx.stroke(); }
    ctx.strokeStyle = '#99dfcc'; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.beginPath();
    let previous;
    for (const row of rows) {
      if (!Number.isFinite(row.wind_kts)) { previous = null; continue; }
      if (!previous || Date.parse(row.time) - Date.parse(previous.time) > 7200000) ctx.moveTo(x(row), y(row));
      else ctx.lineTo(x(row), y(row));
      previous = row;
    }
    ctx.stroke(); ctx.fillStyle = '#a2b2b8'; ctx.font = '9px system-ui';
    ctx.fillText(Math.round(max).toString(), width - 23, 15);
    ctx.fillText('0', width - 23, height - 17);
    const elapsed = Math.round((last - first) / 3600000);
    ctx.fillText(elapsed + 'h before latest reading', 6, height - 3);
    ctx.textAlign = 'right'; ctx.fillText('Latest', width - 30, height - 3);
  }
  document.querySelectorAll('.wind-trend').forEach(canvas => {
    drawTrend(canvas);
    if (window.ResizeObserver) new ResizeObserver(() => drawTrend(canvas)).observe(canvas);
  });

  // Offer new data without losing the user's place, camera, or an unsaved report.
  if (document.body.dataset.demo !== 'true') {
    let revision = null;
    let initiallyLoading = document.body.dataset.ready !== 'true';
    async function poll() {
      try {
        const response = await fetch('/api/status');
        if (!response.ok) return;
        const status = await response.json();
        if ((initiallyLoading && status.ready) || (revision && status.revision !== revision)) {
          document.getElementById('update-notice').hidden = false;
          const loading = document.getElementById('loading-notice');
          if (loading) loading.hidden = true;
          initiallyLoading = false;
        }
        revision = status.revision;
      } catch { /* Last rendered conditions remain available. */ }
    }
    poll();
    window.setInterval(() => { if (!document.hidden) poll(); }, 15000);
  }
  document.getElementById('reload-conditions')?.addEventListener('click', () => location.reload());
})();
