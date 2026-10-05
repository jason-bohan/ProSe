"""Source inventory, full local text and offline search for research packs."""

RESEARCH_JS = r"""
(() => {
  const $ = id => document.getElementById(id);
  let catalog = null, offset = 0, lastQuery = '', serial = 0;
  function node(tag, text, cls) { const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n; }
  async function api(path, body = {}) {
    const r = await fetch('/api/research/' + path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await r.json(); if (!r.ok) throw new Error(data.error || 'Research request failed.'); return data;
  }
  function external(url, title) { if (!/^https?:\/\//.test(url)) return node('span', 'Original file is saved in your local case folder.'); const a = node('a', title); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; }
  function note(s) {
    return [s.category, s.edition || 'Edition: inspect source', s.fetched_at ? 'Retrieved ' + s.fetched_at.slice(0,10) : '', s.scope_note || '', s.refresh_error ? 'Refresh failed: showing previous copy. ' + s.refresh_error : '', ...(s.extraction_warnings || [])].filter(Boolean).join(' · ');
  }
  function showImportReport(report) {
    const box = node('section', '', 'import-summary'); $('import-status').replaceChildren(box);
    if (!report.files.length) { box.append(node('p', 'No files found. Put the ZIP in ' + report.folder + ' and try again.')); return; }
    const ready = report.files.filter(f => f.status === 'ready');
    const pending = report.files.filter(f => f.status !== 'ready');
    box.append(node('h3', ready.length + ' files indexed'));
    box.append(node('p', pending.length ? pending.length + ' files need attention.' : 'All files in this archive were indexed.'));
    for (const f of ready) for (const warning of f.warnings || []) box.append(node('p', f.name + ': ' + warning, 'small'));
    if (pending.length) {
      const groups = new Map();
      for (const f of pending) {
        const reason = f.error.includes('OCR') ? 'Image or scan · needs OCR' :
          f.error.includes('Unsupported') ? 'Unsupported format' :
          f.error.includes('limit') ? 'Size or import limit' : 'Needs review';
        if (!groups.has(reason)) groups.set(reason, []);
        groups.get(reason).push(f);
      }
      const all = node('details'); all.append(node('summary', 'Show file details'));
      for (const [reason, files] of groups) {
        const group = node('details'); group.append(node('summary', files.length + ' · ' + reason));
        const list = node('ul');
        for (const f of files) list.append(node('li', f.name + (f.error ? ' — ' + f.error : '')));
        group.append(list); all.append(group);
      }
      box.append(all);
    }
    box.append(node('p', 'Indexed files are stored locally. Select “Include my imported case documents” in Debate practice to use them.', 'small'));
  }
  async function openSource(id) {
    $('document').hidden = false; $('document-text').replaceChildren(node('p', 'Loading saved text…')); $('document').scrollIntoView({behavior:'smooth'});
    try {
      const data = await api('document', {source_id:id}); const s = data.source;
      $('document-title').textContent = s.title; $('document-meta').textContent = note(s);
      $('document-text').replaceChildren(external(s.url, 'Open original publication'));
      if (s.error) $('document-text').append(node('p', 'Unavailable: ' + s.error));
      for (const p of data.passages) {
        const section = node('section', ''); section.append(node('h3', p.locator + ' · ' + p.citation_id), node('p', p.text, 'source-text'));
        $('document-text').append(section);
      }
    } catch (e) { $('document-text').replaceChildren(node('p', e.message)); }
  }
  function inventory() {
    if (!catalog) return;
    const category = $('category').value, filter = $('inventory-filter').value.trim().toLowerCase();
    const sources = catalog.sources.filter(s => (!category || s.category === category) && (!filter || (s.title + ' ' + s.url).toLowerCase().includes(filter)));
    $('inventory').replaceChildren(); $('inventory-count').textContent = sources.length + ' documents';
    for (const s of sources) {
      const row = node('article', '', 'source-row');
      const button = node('button', s.title); button.type = 'button'; button.addEventListener('click', () => openSource(s.id));
      row.append(button, node('span', s.status === 'ready' ? ' Saved · ' + s.passages + ' passages' : ' Unavailable', 'small'), node('p', note(s), 'small'));
      if (s.error) row.append(node('p', s.error, 'small'));
      $('inventory').append(row);
    }
  }
  async function search(reset = true) {
    if (reset) offset = 0;
    lastQuery = $('query').value.trim();
    const request = ++serial; $('results').replaceChildren(node('p','Searching…'));
    try {
      const data = await api('search', {query:lastQuery, category:$('category').value, offset});
      if (request !== serial) return;
      $('results').replaceChildren(); $('result-count').textContent = data.total + ' matching passages';
      if (!data.results.length) $('results').append(node('p', 'No matching passages. Try specific terms such as revocation, discipline, appeal, or disability.'));
      for (const s of data.results) {
        const row = node('article', '', 'source-row'); const button = node('button', s.title + ' · ' + s.locator); button.type = 'button'; button.addEventListener('click', () => openSource(s.source_id));
        row.append(button, node('p', note(s), 'small'), node('p', s.text, 'source-text'), external(s.url, 'Original source'));
        $('results').append(row);
      }
      $('previous').disabled = offset === 0; $('next').disabled = !data.has_more;
    } catch (e) { if (request === serial) $('results').replaceChildren(node('p', e.message)); }
  }
  $('search-form').addEventListener('submit', e => { e.preventDefault(); search(); });
  $('category').addEventListener('change', () => { inventory(); if (lastQuery) search(); });
  $('inventory-filter').addEventListener('input', inventory);
  $('previous').addEventListener('click', () => { offset = Math.max(0, offset - 20); search(false); });
  $('next').addEventListener('click', () => { offset += 20; search(false); });
  $('close-document').addEventListener('click', () => { $('document').hidden = true; });
  $('import-case').addEventListener('click', async () => {
    $('import-case').disabled = true; $('import-status').textContent = 'Importing local case documents…';
    try {
      const r = await api('import-case');
      showImportReport(r);
      catalog = await api('catalog'); inventory();
      if (catalog.case_ready && !Array.from($('category').options).some(o => o.value === 'Your case documents')) { const o = node('option','Your case documents'); o.value = 'Your case documents'; $('category').append(o); }
      $('coverage').textContent = catalog.national_ready + ' national sources · ' + catalog.case_ready + ' case files · ' + catalog.passages.toLocaleString() + ' passages · ' + catalog.unavailable + ' unavailable';
    } catch (e) { $('import-status').replaceChildren(node('p', e.message)); }
    finally { $('import-case').disabled = false; }
  });
  for (const b of document.querySelectorAll('[data-query]')) b.addEventListener('click', () => { $('query').value = b.dataset.query; search(); });
  api('catalog').then(data => {
    catalog = data; $('coverage').textContent = data.national_ready + ' national sources · ' + data.case_ready + ' case files · ' + data.passages.toLocaleString() + ' passages · ' + data.unavailable + ' unavailable';
    $('scope').textContent = data.scope;
    for (const [c, count] of Object.entries(data.categories)) { const o = node('option', c + ' (' + count + ')'); o.value = c; $('category').append(o); }
    inventory();
    if (!data.installed) $('coverage').textContent = 'This research pack has not been installed. See RESEARCH.md for the importer.';
  }).catch(e => { $('coverage').textContent = e.message; });
})();
"""


def render_research_page(css: str, nav: str) -> str:
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Research · LexGlasses</title>
<style>{css}
.source-row {{padding:1rem 0;border-bottom:1px solid #bbb5}} .source-row button {{text-align:left;max-width:100%}}
.source-text {{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}} #inventory {{max-height:65vh;overflow:auto}}
select,input {{max-width:100%}} .research-actions {{display:flex;gap:.6rem;flex-wrap:wrap;margin:.7rem 0}}
.import-summary {{padding:.85rem 1rem;margin:.8rem 0;border:1px solid #bbb8;border-left:4px solid #39866f;border-radius:.35rem}}
.import-summary h3 {{margin:.1rem 0 .3rem}} .import-summary details {{margin-top:.65rem}}
.import-summary ul {{margin:.5rem 0 .2rem;padding-left:1.5rem}} .import-summary li {{margin:.3rem 0;overflow-wrap:anywhere}}
</style></head><body><div class="container"><header class="header"><div><h1>Research library</h1>
<div class="badge">Saved sources · searchable offline</div></div>{nav}</header>
<main id="main"><section class="card"><h2>Scouting America</h2><p id="coverage" role="status">Loading coverage…</p><p id="scope" class="small"></p>
<p>Read the national guides here, then <a href="/practice?topic=scouting">practice a Scout-removal discussion</a>. The coach retrieves passages each turn. Legal references are separately labeled and optional in practice.</p>
<details><summary>Import your situation documents</summary><p>Download the Google Drive folder as a ZIP and put it in <code>.prose/scouting-case</code>. PDF, Word, PowerPoint, Excel, text, CSV, JSON and email files are supported. Photos and scans need OCR before they can be searched.</p><button id="import-case">Import case folder</button><div id="import-status" role="status" aria-live="polite"></div><p class="small">Import saves and indexes locally. Enable “Include my imported case documents” in a debate to send relevant excerpts to your selected model.</p></details>
<label for="category">Category</label><select id="category"><option value="">All categories</option></select>
<form id="search-form"><label for="query">Search the saved text</label><input id="query" maxlength="500" placeholder="membership revocation appeal" required><button type="submit">Search</button></form>
<div class="research-actions"><button data-query="revocation membership denial appeal">Membership and removal</button><button data-query="discipline bullying constructive">Conduct</button><button data-query="disability accommodation inclusion">Inclusion</button><button data-query="board review appeal advancement">Advancement</button></div>
<p class="small">Search finds passages containing any of your terms. PDFs use file page numbers; printed page numbers can differ. Text extraction may omit images or scanned pages.</p>
<p id="result-count" role="status"></p><div id="results"></div><div class="research-actions"><button id="previous" disabled>Previous</button><button id="next" disabled>Next</button></div></section>
<section class="card" id="document" hidden><button id="close-document">Close document</button><h2 id="document-title"></h2><p id="document-meta" class="small"></p><div id="document-text"></div></section>
<section class="card"><h2>Document inventory</h2><p>Includes unavailable sources and older documents still linked by the publisher. A saved copy is a snapshot, not a promise that every rule is current or applies to your unit.</p><label for="inventory-filter">Filter document titles</label><input id="inventory-filter" placeholder="charter, renewal, safety…"><p id="inventory-count"></p><div id="inventory"></div></section></main><footer>DISCLAIMER: research summaries are leads to verify, not conclusions. Not legal advice.</footer></div><script>{RESEARCH_JS}</script></body></html>'''
