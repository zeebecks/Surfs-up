/* Forecast snapshots are rendered from the same cached data as the first view. */
(() => {
  'use strict';
  const shell = document.querySelector('.spot-detail-shell');
  if (!shell) return;
  const conditions = shell.querySelector('.conditions-panel');
  const rating = shell.querySelector('.rating-panel');
  const table = shell.querySelector('.hourly-table');
  const scroll = shell.querySelector('.forecast-scroll');
  const columns = [...table.querySelectorAll('colgroup col')].slice(1);
  const headers = [...table.querySelectorAll('[data-hour-column]')];
  const windCells = [...table.querySelectorAll('.wind-cell')];
  const range = shell.querySelector('[data-forecast-range]');
  let selectedHour = Number(range.value);

  document.addEventListener('forecast:change', event => {
    const {hour, snapshot} = event.detail;
    if (!snapshot?.conditions_html || !snapshot?.rating_html) return;
    if (hour !== selectedHour) {
      conditions.innerHTML = snapshot.conditions_html;
      rating.innerHTML = snapshot.rating_html;
      selectedHour = hour;
    }
    headers.forEach((header, index) => {
      const selected = index === hour;
      header.classList.toggle('selected-hour', selected);
      header.querySelector('.hour-choice').setAttribute('aria-pressed', String(selected));
      header.querySelector('.selected-hour-label').hidden = !selected;
      columns[index].classList.toggle('forecast-hour-selected', selected);
      windCells[index].classList.toggle('is-selected', selected);
    });
    const backLink = shell.querySelector('.back-link');
    backLink.href = '/?h=' + hour;

    // Keep the selected hour in view without scrolling the page vertically.
    const header = headers[hour];
    const bounds = scroll.getBoundingClientRect();
    const cell = header.getBoundingClientRect();
    const labelWidth = table.querySelector('thead th').getBoundingClientRect().width;
    if (cell.left < bounds.left + labelWidth || cell.right > bounds.right) {
      scroll.scrollLeft += cell.left - bounds.left - labelWidth - 12;
    }
  });

  shell.querySelectorAll('[data-forecast-hour]').forEach(button => {
    button.addEventListener('click', () => {
      range.value = button.dataset.forecastHour;
      range.dispatchEvent(new Event('input', {bubbles: true}));
      range.dispatchEvent(new Event('change', {bubbles: true}));
    });
  });
})();
