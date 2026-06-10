// Presentational shell behavior: collapsible analysis panels and the Advanced
// Analysis toggle. Kept separate from the data/view layer (layout.js + views)
// so the markup and these interactions can be restyled or restructured during a
// redesign without touching analysis logic.
(function () {
  // ── Collapsible panels ──────────────────────────────────────────
  document.querySelectorAll('.panel-collapsible').forEach(function (panel, index) {
    var head = panel.querySelector('.panel-head');
    var body = panel.querySelector('.panel-body');
    var icon = panel.querySelector('.panel-toggle-icon');
    var title = panel.querySelector('h2');
    if (!head || !body || !icon) return;

    if (!body.id) {
      body.id = (title && title.id ? title.id : 'panel-' + index) + '-body';
    }

    icon.classList.add('panel-collapse-toggle');
    head.setAttribute('role', 'button');
    head.setAttribute('tabindex', '0');
    head.setAttribute('aria-controls', body.id);

    function syncPanelState() {
      var expanded = panel.classList.contains('is-expanded');
      var label = title ? title.textContent.trim() : 'panel';
      icon.textContent = expanded ? '−' : '+';
      head.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      head.setAttribute('aria-label', (expanded ? 'Collapse ' : 'Expand ') + label);
      body.inert = !expanded;
      body.setAttribute('aria-hidden', expanded ? 'false' : 'true');
    }

    function togglePanel() {
      var expanded = panel.classList.toggle('is-expanded');
      syncPanelState();
      // Notify views of resize after animation settles.
      if (expanded) {
        setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 320);
      }
    }

    head.addEventListener('click', function (event) {
      var target = event.target;
      if (target && target.nodeType !== 1) target = target.parentElement;
      if (target && target.closest('a, input, select, textarea, label')) return;
      togglePanel();
    });
    head.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      togglePanel();
    });
    syncPanelState();
  });

  // ── Advanced Analysis toggle ────────────────────────────────────
  var advBtn = document.getElementById('advanced-toggle');
  var advSection = document.getElementById('advanced-views');
  if (!advBtn || !advSection) return;
  function setAdvancedOpen(open) {
    advSection.style.display = open ? 'grid' : 'none';
    advBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    advBtn.querySelector('.toggle-chevron').textContent = open ? '▴' : '▾';
    if (open) {
      setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 50);
    }
  }
  advBtn.addEventListener('click', function () {
    var open = advSection.style.display !== 'none';
    setAdvancedOpen(!open);
  });
}());
