/* Apply the already-loaded forecast while keeping map, favorites, and gallery state. */
(() => {
  'use strict';
  const list = document.querySelector('.home-shell .spot-list');
  if (!list) return;
  const cards = new Map([...list.querySelectorAll('.spot-card')].map(card => [card.dataset.spotId, card]));
  const parsed = document.createElement('template');

  document.addEventListener('forecast:change', event => {
    const snapshot = event.detail?.snapshot;
    if (!Array.isArray(snapshot?.items)) return;
    let focusedFavorite;
    for (const item of snapshot.items) {
      const card = cards.get(item.id);
      if (!card || typeof item.html !== 'string') continue;
      parsed.innerHTML = item.html;
      const next = parsed.content.querySelector('.spot-card');
      if (!next || next.dataset.spotId !== item.id) continue;

      // These exact buttons retain their favorite state, focus, and listeners.
      const favorite = card.querySelector('[data-favorite]');
      const newFavorite = next.querySelector('[data-favorite]');
      if (document.activeElement === favorite) focusedFavorite = favorite;
      if (favorite && newFavorite) newFavorite.replaceWith(favorite);
      card.dataset.windScore = next.dataset.windScore;
      card.dataset.surfScore = next.dataset.surfScore;
      card.replaceChildren(...next.childNodes);
    }

    // Existing sorting uses the updated scores; saved filters and card IDs stay put.
    const sort = document.getElementById('spot-sort');
    if (sort) sort.dispatchEvent(new Event('change'));
    focusedFavorite?.focus({preventScroll: true});
  });
})();
