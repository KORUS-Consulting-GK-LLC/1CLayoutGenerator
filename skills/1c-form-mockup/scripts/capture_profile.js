// Visibility profile of the open 1C web-client form (platform 8.3, «Такси»).
// Open the form in the published base, press F12 -> Console, paste this file, press Enter.
// The JSON printed (and copied to the clipboard when allowed) goes to
// <profiles-dir>/<configuration>.<Folder>.<Object>.<Form>.json
// Visit each tab that has a table and run it again, save each output, then join them:
//   python form_html.py merge-profile run1.json run2.json --out <profiles-dir>/<configuration>.<Folder>.<Object>.<Form>.json
(function () {
  const norm = s => (s || '').replace(/ /g, ' ').replace(/\s+/g, ' ').trim();
  const box = e => e.getBoundingClientRect();
  const seen = e => { const r = box(e); const c = getComputedStyle(e); return r.width > 0 && r.height > 0 && c.visibility !== 'hidden'; };
  const side = Math.max(...[...document.querySelectorAll('.themeBox, .ePrimaryBack.jumpsV')].filter(seen).map(e => box(e).right), 0);
  const inForm = e => seen(e) && box(e).x >= side - 1 && box(e).y > 60;
  const uniq = a => [...new Set(a.filter(Boolean))];
  const profile = { source: location.origin + location.pathname + ' — ' + new Date().toISOString().slice(0, 10),
                    nav: [], tabs: [], buttons: [], labels: [], tables: {}, table_buttons: {} };
  profile.nav = uniq([...document.querySelectorAll('.navigationItemName')].filter(inForm).map(e => norm(e.textContent)));
  profile.tabs = uniq([...document.querySelectorAll('.tabsItemTitle')].filter(inForm)
    .map(e => e.getAttribute('data-content') || norm(e.textContent)));
  profile.labels = uniq([...document.querySelectorAll('label')].filter(inForm).map(e => norm(e.textContent)));
  const grids = [...document.querySelectorAll('.grid')].filter(g => inForm(g) && g.querySelector('.gridHead'));
  grids.forEach((g, i) => {
    const cols = [...g.querySelectorAll('.gridHead .gridBoxTitle')].filter(e => box(e).height > 0)
      .map(e => norm(e.textContent) || '[pic]');
    const tab = [...document.querySelectorAll('.tabsItem.select .tabsItemTitle')].find(inForm);
    const name = (tab && (tab.getAttribute('data-content') || '').replace(/\s*\(\d+\)$/, '')) || ('Таблица' + (i + 1));
    profile.tables[grids.length > 1 ? name + ' ' + (i + 1) : name] = cols;
  });
  // A button sits on a table's command bar when a grid starts less than 120px below its top.
  [...document.querySelectorAll('a.press')].filter(inForm).forEach(b => {
    const t = norm(b.textContent) || (b.getAttribute('title') ? '[' + b.getAttribute('title') + ']' : '');
    if (!t || t === 'More actions' || t === 'Еще') return;   // «Еще» menu and untitled icons
    const label = (b.classList.contains('pressDefault') ? '*' : '') + t;
    const r = box(b);
    const gi = grids.findIndex(g => { const gr = box(g); return gr.top > r.top && gr.top - r.top < 120; });
    if (gi >= 0) {
      const key = Object.keys(profile.tables)[gi];
      (profile.table_buttons[key] = profile.table_buttons[key] || []).includes(label) || profile.table_buttons[key].push(label);
    } else if (!profile.buttons.includes(label)) {
      profile.buttons.push(label);
    }
  });
  const json = JSON.stringify(profile, null, 1);
  try { copy(json); } catch (e) { /* copy() exists only in DevTools */ }
  console.log(json);
  return json;
})();
