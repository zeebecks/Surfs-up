/* Hourly forecast navigation uses the timeline already embedded in the page. */
(() => {
  'use strict';

  function initializeTimeline() {
    const control = document.querySelector('.forecast-time-control');
    const source = document.getElementById('forecast-timeline');
    if (!control || !source) return;
    let timeline;
    try { timeline = JSON.parse(source.textContent); } catch { return; }
    if (!Array.isArray(timeline) || timeline.length !== 49 || timeline.some(hour => !hour)) return;

    const slider = control.querySelector('[data-forecast-range]');
    const reset = control.querySelector('[data-forecast-now]');
    const caption = control.querySelector('[data-forecast-caption]');
    const offset = control.querySelector('[data-forecast-offset]');
    const announcement = control.querySelector('[data-forecast-announcement]');
    if (!slider || !reset || !caption || !offset) return;
    control.classList.add('forecast-enhanced');

    let selected = null;
    let pending = Number(slider.value);
    let animationFrame = null;

    function render(hour) {
      const snapshot = timeline[hour];
      const label = hour === 0 ? 'Now' : `+${hour}h`;
      const local = snapshot.local_label || snapshot.caption || '';
      slider.value = hour;
      slider.setAttribute('aria-valuetext', `${label}: ${local}`);
      control.style.setProperty('--forecast-position', `${hour / 48 * 100}%`);
      offset.textContent = label;
      if (snapshot.caption) caption.textContent = snapshot.caption;
      reset.classList.toggle('active', hour === 0);
      if (hour === 0) reset.setAttribute('aria-current', 'true');
      else reset.removeAttribute('aria-current');
      if (selected === hour) return;
      selected = hour;
      document.dispatchEvent(new CustomEvent('forecast:change', {detail: {hour, snapshot}}));
    }

    function queueRender(hour) {
      pending = Math.min(48, Math.max(0, Math.round(hour)));
      if (animationFrame !== null) return;
      animationFrame = requestAnimationFrame(() => {
        animationFrame = null;
        render(pending);
      });
    }

    function commit(hour) {
      queueRender(hour);
      const url = new URL(window.location.href);
      url.searchParams.set('h', String(hour));
      window.history.replaceState(window.history.state, '', url);
      if (announcement) {
        announcement.textContent = timeline[hour].caption || `${hour === 0 ? 'Now' : `+${hour} hours`}: ${timeline[hour].local_label || ''}`;
      }
    }

    slider.addEventListener('input', () => queueRender(Number(slider.value)));
    slider.addEventListener('change', () => commit(Number(slider.value)));
    control.querySelector('form').addEventListener('submit', event => {
      event.preventDefault();
      commit(Number(slider.value));
    });
    reset.addEventListener('click', event => {
      event.preventDefault();
      slider.value = 0;
      commit(0);
    });
    window.addEventListener('popstate', () => {
      const value = new URL(window.location.href).searchParams.get('h');
      const hour = value !== null && /^\d+$/.test(value) && Number(value) <= 48 ? Number(value) : 0;
      queueRender(hour);
    });

    // Defer the initial event until every page-specific listener is installed.
    queueRender(Number(slider.value));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initializeTimeline, {once:true});
  else initializeTimeline();
})();
