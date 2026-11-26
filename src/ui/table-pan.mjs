// Track the stable scroll container, not a ticker row: live updates recycle rows.
export function enableTablePan(scroller) {
  let drag = null, suppressClick = false;

  scroller.addEventListener('pointerdown', e => {
    suppressClick = false;
    if (e.pointerType !== 'mouse' || e.button !== 0 ||
        !e.target.closest('tbody td:not(.ctl, .chartcell, .empty, .pad)')) return;
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY,
             left: scroller.scrollLeft, top: scroller.scrollTop, captured: false };
  });
  window.addEventListener('pointermove', e => {
    if (!drag || e.pointerId !== drag.id) return;
    if (!(e.buttons & 1)) { finish(); return; }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!dx && !dy && !drag.captured) return;
    if (!drag.captured) {
      scroller.setPointerCapture(e.pointerId);
      scroller.classList.add('panning');
      drag.captured = true;
    }
    scroller.scrollLeft = drag.left - dx;
    scroller.scrollTop = drag.top - dy;
  });
  function finish(e) {
    if (!drag || (e?.pointerId !== undefined && e.pointerId !== drag.id)) return;
    const { id, captured } = drag;
    drag = null;
    suppressClick = captured;
    scroller.classList.remove('panning');
    if (scroller.hasPointerCapture(id)) scroller.releasePointerCapture(id);
  }
  for (const evt of ['pointerup', 'pointercancel', 'blur']) window.addEventListener(evt, finish);
  scroller.addEventListener('lostpointercapture', finish);
  scroller.addEventListener('click', e => {
    if (!suppressClick || e.detail === 0) return;
    suppressClick = false;
    e.preventDefault();
    e.stopImmediatePropagation();
  }, true);
}
