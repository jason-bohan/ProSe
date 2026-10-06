"""Vocabulary notebook and active-recall practice page."""

from __future__ import annotations

VOCAB_CSS = """
.vocab-grid{display:grid;grid-template-columns:minmax(270px,.85fr) minmax(0,1.4fr);gap:1.25rem;align-items:start}
.vocab-grid h2{font-weight:700;font-size:1.25rem;margin:0 0 .8rem}.vocab-grid label{font-weight:400;text-transform:none}
.vocab-grid textarea{min-height:75px;font-family:inherit}.vocab-grid input[type=text]{font-family:inherit}
.vocab-grid [hidden]{display:none!important}.vocab-grid button:disabled{opacity:.4;cursor:default}
.vocab-grid .btn-row{flex-wrap:wrap}.vocab-grid .pair{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
.vocab-grid .small{font-size:.85rem;color:var(--g9)}.vocab-grid .word-list{max-height:420px;overflow:auto;margin-top:1rem}
.word-list button{display:block;text-align:left;width:100%;background:var(--w);color:var(--k);border:0;border-bottom:1px solid var(--g1);padding:.65rem}
.word-list button.active{background:var(--face);box-shadow:inset 3px 0 0 var(--o)}.word-list button span{display:block;font-size:.75rem;color:var(--g9)}
.vocab-grid .review{background:var(--paper);border:1px solid var(--k)}.review h2{font-size:2rem;letter-spacing:-.02em}
.vocab-grid .check{display:flex;align-items:center;gap:.5rem}.vocab-grid fieldset{border:0;padding:0;margin:0;min-width:0}
.vocab-grid .row{margin-bottom:.8rem}.vocab-grid :focus-visible{outline:2px solid var(--o);outline-offset:3px}
.vocab-grid .definition{font-size:1.1rem}.vocab-grid .word-source{font-size:.78rem;overflow-wrap:anywhere}
#vocab-notice{min-height:1.6rem}#vocab-notice.error{color:#a21b22}.resource-list li{margin-bottom:.7rem}
.category-buttons{display:grid;grid-template-columns:1fr 1fr;gap:.4rem;margin:.8rem 0}.category-buttons button{font-size:.8rem;background:var(--w);color:var(--k);text-align:left;padding:.65rem;border:1px solid var(--g1)}.category-buttons button[aria-pressed=true]{background:var(--w);outline:2px solid var(--o)}.library-results{max-height:360px;overflow:auto}.library-results button{display:block;width:100%;text-align:left;margin:.3rem 0;background:var(--w);border:1px solid var(--g1);color:var(--k)}
.vocab-grid blockquote{border-left:3px solid var(--face2);padding-left:1rem;margin-left:0;white-space:pre-wrap}
@media(max-width:780px){.vocab-grid{grid-template-columns:1fr}.vocab-grid .pair{grid-template-columns:1fr}.container{padding:1rem}}
"""

VOCAB_JS = r"""
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let listing = null, editing = null, review = null, lookup = null, busy = false;
  let notebookPage = 0, libraryOffset = 0, libraryQuery = '', libraryHasMore = false;
  const notice = (message, error=false) => { $('vocab-notice').textContent = message; $('vocab-notice').classList.toggle('error',error); };
  async function api(action, body={}) {
    const response = await fetch('/api/vocabulary/' + action, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    let data; try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) throw new Error(data && data.error ||
      'Vocabulary request failed (HTTP ' + response.status + ').');
    if (!data || typeof data !== 'object') throw new Error('Vocabulary server returned an invalid response.');
    return data;
  }
  function lock(value) {
    busy = value;
    for (const el of document.querySelectorAll('[data-lock]')) el.disabled = value;
    $('library-prev').disabled=value || libraryOffset===0;
    $('library-next').disabled=value || !libraryHasMore;
  }
  async function action(fn) {
    if (busy) return; lock(true);
    try { await fn(); } catch (error) { notice(error.message, true); }
    finally { lock(false); }
  }
  const cleanLink = url => { try { const u = new URL(url); return ['https:','http:'].includes(u.protocol) ? u.href : ''; } catch (_) { return ''; } };
  function attribution(element, source) {
    element.replaceChildren();
    if (!source || !source.name) { element.textContent = 'Your notes / original ProSe starter content.'; return; }
    const link = document.createElement('a'); link.textContent = source.name;
    const url = cleanLink(source.url); if (url) { link.href=url; link.target='_blank'; link.rel='noopener noreferrer'; }
    element.append(link);
    if (source.license) {
      const license = document.createElement('a'); license.textContent=source.license;
      const target = cleanLink(source.license_url); if (target) { license.href=target; license.target='_blank'; license.rel='noopener noreferrer'; }
      element.append(' · ',license);
    }
    if (source.note) element.append(' · ' + source.note);
  }
  async function refresh() {
    listing = await api('list');
    $('vocab-count').textContent = listing.words.length + ' words · ' + listing.due + ' due for recall';
    $('online-lookups').checked = listing.online;
    $('offline-status').textContent = listing.offline_dictionary ? 'Offline dictionary installed. Saved words and recall practice work without internet while this local app is running.' : 'Saved words work offline. Install Open English WordNet for additional offline lookups (see SETUP.md).';
    const selected=$('category-filter').value;
    $('category-filter').replaceChildren(new Option('All categories',''));
    $('category-buttons').replaceChildren();
    for(const category of listing.categories) {
      $('category-filter').append(new Option(category+' ('+listing.category_counts[category]+')',category));
      const button=document.createElement('button');button.type='button';button.textContent=category+' · '+listing.category_counts[category];
      button.dataset.category=category;button.setAttribute('aria-pressed',String(category===selected));
      button.onclick=()=>{if(busy)return;$('category-filter').value=category;filterChanged();};
      $('category-buttons').append(button);
    }
    if(listing.categories.includes(selected))$('category-filter').value=selected;
    renderWords();
  }
  function filteredWords() {
    if(!listing)return [];
    const query=$('word-filter').value.trim().toLowerCase(),level=$('level-filter').value,category=$('category-filter').value;
    return listing.words.filter(card=>(!level || card.level===level) && (!category || card.category===category) && (!query || [card.word,card.definition,card.theme,card.root,card.family].join(' ').toLowerCase().includes(query)));
  }
  function filterChanged() {notebookPage=0;renderWords();nextReview();}
  function renderWords() {
    if (!listing) return;
    const filtered=filteredWords();
    notebookPage=Math.min(notebookPage,Math.max(0,Math.ceil(filtered.length/40)-1));
    const log = $('word-list'); log.replaceChildren();
    for (const card of filtered.slice(notebookPage*40,notebookPage*40+40)) {
      const button=document.createElement('button'); button.type='button';
      if (editing && editing.word === card.word) button.className='active';
      button.textContent=(card.focus?'★ ':'')+card.word;
      const meta=document.createElement('span'); meta.textContent=[card.theme,card.level,card.reviews+' reviews',card.uses+' debate uses'].filter(Boolean).join(' · ');
      button.append(meta); button.onclick=()=>{ if(!busy) edit(card); }; log.append(button);
    }
    if (!log.children.length) log.textContent='No matching words.';
    $('notebook-page').textContent=filtered.length+' matching words · Page '+(notebookPage+1)+' / '+Math.max(1,Math.ceil(filtered.length/40));
    $('notebook-prev').disabled=notebookPage===0;$('notebook-next').disabled=(notebookPage+1)*40>=filtered.length;
    for(const button of $('category-buttons').children)button.setAttribute('aria-pressed',String(button.dataset.category===$('category-filter').value));
  }
  function edit(card) {
    editing=card ? {...card} : null;
    $('word-form').reset();
    for (const el of $('word-form').elements) if (el.name && el.type!=='checkbox') el.value=card ? (card[el.name] || '') : '';
    $('level').value=(card && card.level) || 'Essential';
    $('word').readOnly=Boolean(card); $('focus-word').checked=Boolean(card && card.focus);
    $('word-editor').open=true; $('editor-heading').textContent=card ? 'Your word: '+card.word : 'Add a word';
    attribution($('word-attribution'), card && card.attribution);
    renderWords();
  }
  $('word-filter').addEventListener('input',filterChanged);
  $('level-filter').addEventListener('change',filterChanged);
  $('category-filter').addEventListener('change',filterChanged);
  $('notebook-prev').onclick=()=>{if(!busy){notebookPage--;renderWords();}};
  $('notebook-next').onclick=()=>{if(!busy){notebookPage++;renderWords();}};
  $('new-word').onclick=()=>{edit(null);$('word').focus();};
  $('word-form').onsubmit=event=>{event.preventDefault();
    const card=Object.fromEntries(new FormData(event.target));action(async()=>{
    card.focus=$('focus-word').checked; card.attribution=editing ? editing.attribution : {};
    if (editing) card.revision=editing.revision;
    const saved=await api('save',card); await refresh(); edit(saved);
    notice('Saved on this computer. Your recall schedule is preserved.');
  });};
  $('lookup-form').onsubmit=event=>{event.preventDefault();action(async()=>{
    notice('Looking up the word…');
    lookup=await api('lookup',{word:$('lookup-word').value});
    const select=$('lookup-sense');select.replaceChildren();
    lookup.senses.forEach((sense,index)=>{const option=document.createElement('option');option.value=index;option.textContent=(sense.part_of_speech?sense.part_of_speech+': ':'')+sense.definition;select.append(option);});
    $('lookup-result').hidden=false; showSense(); notice('Definition from '+lookup.availability+'.');
  });};
  function showSense() {
    if (!lookup) return;
    const sense=lookup.senses[Number($('lookup-sense').value)];
    $('lookup-definition').textContent=sense.definition;
    $('lookup-example').textContent=sense.example;
    $('lookup-related').textContent=(lookup.pronunciation ? lookup.pronunciation+' · ' : '')+(sense.synonyms.length ? 'Related: '+sense.synonyms.join(', ') : '');
    attribution($('lookup-source'),lookup.source);
  }
  $('lookup-sense').onchange=showSense;
  $('use-definition').onclick=()=>{
    if(!lookup) return;
    const existing=listing.words.find(card=>card.word===lookup.word), sense=lookup.senses[Number($('lookup-sense').value)];
    edit(existing || null);
    if (!editing) editing={word:lookup.word,attribution:lookup.source};
    else editing.attribution=lookup.source;
    $('word').value=lookup.word; $('definition').value=sense.definition; $('example').value=sense.example;
    $('part-of-speech').value=sense.part_of_speech;
    attribution($('word-attribution'),lookup.source);
    notice('Definition copied to your word form. Add your notes and save.');
  };
  $('online-lookups').onchange=()=>action(async()=>{
    await api('settings',{online:$('online-lookups').checked}); await refresh();
    notice(listing.online?'Online lookup enabled, with an offline fallback. Only the lookup word is sent.':'Offline mode: dictionary requests stay on this computer.');
  });
  function nextReview() {
    const now=Math.floor(Date.now()/1000);
    review=filteredWords().find(card=>card.due<=now) || null;
    $('review-content').hidden=!review; $('review-empty').hidden=Boolean(review);
    $('review-answer').hidden=true; $('review-ratings').hidden=true; $('reveal-answer').hidden=false;
    $('review-own-words').value=''; $('review-own-example').value='';
    if (review) { $('review-word').textContent=review.word; $('review-meta').textContent=[review.theme,review.level].filter(Boolean).join(' · '); }
  }
  $('begin-review').onclick=()=>action(async()=>{await refresh();nextReview();notice(review?'Explain the word before revealing the answer.':'You are caught up. Add a word or practice in a debate.');});
  $('reveal-answer').onclick=()=>{
    if(!review) return;
    $('review-definition').textContent=review.definition; $('review-example').textContent=review.example;
    $('review-root').textContent=[review.root,review.family].filter(Boolean).join(' · ');
    attribution($('review-source'),review.attribution);
    $('review-answer').hidden=false;$('review-ratings').hidden=false;$('reveal-answer').hidden=true;
  };
  for(const button of document.querySelectorAll('[data-rating]')) button.onclick=()=>action(async()=>{
    if(!review) return;
    const result={word:review.word,revision:review.revision,rating:button.dataset.rating};
    if($('review-own-words').value.trim()) result.own_words=$('review-own-words').value;
    if($('review-own-example').value.trim()) result.own_example=$('review-own-example').value;
    await api('review',result);
    await refresh(); nextReview(); notice('Recall saved. Again returns in 10 minutes; other ratings schedule a later day.');
  });
  $('say-word').onclick=()=>{
    if(!review || !('speechSynthesis' in window)) {notice('Speech playback is unavailable in this browser.',true);return;}
    speechSynthesis.cancel(); const speech=new SpeechSynthesisUtterance(review.word);speech.lang='en-US';
    let name='';try{name=localStorage.getItem('prose-voice')||localStorage.getItem('prose-hud-voice')||'';}catch(_){}
    if(name){const v=speechSynthesis.getVoices().find(x=>x.name===name);if(v){speech.voice=v;speech.lang=v.lang;}}
    speechSynthesis.speak(speech);
  };
  $('import-file').onchange=()=>action(async()=>{
    const file=$('import-file').files[0];if(!file)return;
    if(file.size>16000000)throw new Error('Import limit is 16 MB.');
    const result=await api('import',JSON.parse(await file.text()));await refresh();nextReview();
    notice(result.added+' words restored/added; '+result.kept_existing+' existing edited words kept.');$('import-file').value='';
  });
  async function browseLibrary() {
    const result=await api('library',{query:libraryQuery,offset:libraryOffset});
    libraryHasMore=result.has_more;
    $('library-count').textContent=result.installed ? result.total.toLocaleString()+' offline dictionary entries · '+result.matched.toLocaleString()+' match this prefix' : 'Install the offline dictionary to browse more words. The themed study collections above already work offline.';
    $('library-page').textContent=result.words.length ? (libraryOffset+1)+'–'+(libraryOffset+result.words.length)+' of '+result.matched : 'No results';
    $('library-results').replaceChildren();
    for(const item of result.words) {
      const button=document.createElement('button');button.type='button';
      button.textContent=item.word+' — '+(item.senses[0]?.definition || '');
      button.onclick=()=>{if(busy)return;
        lookup={...item,source:{...result.source,url:'https://en-word.net/view/lemma/'+encodeURIComponent(item.word)},availability:'offline dictionary'};
        $('lookup-word').value=item.word;
        const select=$('lookup-sense');select.replaceChildren();
        item.senses.forEach((sense,index)=>select.append(new Option((sense.part_of_speech?sense.part_of_speech+': ':'')+sense.definition,index)));
        $('lookup-result').hidden=false;showSense();$('lookup-result').scrollIntoView({behavior:'smooth',block:'center'});
      };
      $('library-results').append(button);
    }
  }
  $('library-form').onsubmit=event=>{event.preventDefault();action(async()=>{libraryQuery=$('library-query').value.trim();libraryOffset=0;await browseLibrary();});};
  $('library-prev').onclick=()=>action(async()=>{libraryOffset=Math.max(0,libraryOffset-30);await browseLibrary();});
  $('library-next').onclick=()=>action(async()=>{if(libraryHasMore){libraryOffset+=30;await browseLibrary();}});
  window.addEventListener('pagehide',()=>{if('speechSynthesis' in window)speechSynthesis.cancel();});
  action(async()=>{await refresh();nextReview();await browseLibrary();
    const selected=new URLSearchParams(location.search).get('word');
    if(selected){const card=listing.words.find(item=>item.word===selected);if(card)edit(card);$('lookup-word').value=selected;}
  });
})();
"""


def render_vocabulary_page(css: str, nav: str) -> str:
    body = """
<p>Turn words you recognize into words you can use. Learn the meaning, explain it simply, then try it in a real argument.</p>
<div id="vocab-notice" role="status" aria-live="polite"></div><main id="main" class="vocab-grid"><div>
<section class="card"><h2>Your word notebook</h2><p id="vocab-count" class="small">Loading saved words…</p>
<p class="small">Browse themed study collections. Category and difficulty filters also choose your recall practice.</p><div id="category-buttons" class="category-buttons" aria-label="Vocabulary categories"></div>
<div class="btn-row"><button id="new-word" data-lock>New word</button><a href="/practice">Practice in a debate →</a></div>
<form onsubmit="return false"><label for="word-filter">Search words, roots or themes</label><input id="word-filter" type="text" placeholder="e.g. evidence or cred">
<label for="category-filter">Category</label><select id="category-filter"><option value="">All categories</option></select><label for="level-filter">Level</label><select id="level-filter"><option value="">All levels</option><option>Essential</option><option>Intermediate</option><option>Advanced</option></select></form>
<div id="word-list" class="word-list"></div><p id="notebook-page" class="small"></p><div class="btn-row"><button id="notebook-prev" type="button">Previous</button><button id="notebook-next" type="button">Next</button></div><p class="small">★ Focus words are available to your debate coach. It takes the first three selected words when you start a new practice.</p></section>
<section class="card"><h2>Explore the full offline dictionary</h2><p id="library-count" class="small"></p><form id="library-form"><label for="library-query">Word starts with</label><div class="btn-row"><input id="library-query" type="text" maxlength="80" placeholder="e.g. argu, corrobor, or sub"><button type="submit" data-lock>Browse</button></div></form><div id="library-results" class="library-results"></div><p id="library-page" class="small"></p><div class="btn-row"><button id="library-prev" type="button">Previous</button><button id="library-next" type="button">Next</button></div><p class="small">Select a word, choose its meaning, then use that definition in your notebook. Open English WordNet Community · CC BY 4.0. This general dictionary is separate from the themed study collections.</p></section>
<section class="card"><h2>Dictionary lookup</h2><label class="check"><input id="online-lookups" type="checkbox" data-lock> Use online dictionary when available</label>
<p class="small" id="offline-status"></p><form id="lookup-form"><label for="lookup-word">Word or phrase</label><div class="btn-row"><input id="lookup-word" type="text" maxlength="80" required placeholder="corroborate"><button type="submit" data-lock>Look up</button></div></form>
<div id="lookup-result" hidden><label for="lookup-sense">Choose the meaning you want to learn</label><select id="lookup-sense"></select><p class="definition" id="lookup-definition"></p><blockquote id="lookup-example"></blockquote><p class="small" id="lookup-related"></p><p id="lookup-source" class="word-source"></p><button id="use-definition" data-lock>Use this definition</button></div>
<p class="small">Online definitions: <a href="https://freedictionaryapi.com/" target="_blank" rel="noopener noreferrer">FreeDictionaryAPI.com / Wiktionary</a> (<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>). Offline: <a href="https://en-word.net/">Open English WordNet Community</a>, derived from Princeton WordNet (<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>). Sources stay attached to saved definitions and exports.</p></section>
<section class="card"><h2>Back up your learning</h2><div class="btn-row"><a href="/api/vocabulary/export" download="prose-vocabulary.json">Download JSON backup</a><a href="/api/vocabulary/anki" download="prose-vocabulary.txt">Export for Anki</a></div>
<label for="import-file">Import a ProSe JSON backup (16 MB max)</label><input id="import-file" type="file" accept=".json,application/json" data-lock>
<p class="small">Import restores new words and untouched starter cards; existing edited words are kept. JSON retains recall dates and usage history. Anki text exports card content, not scheduling history.</p></section></div><div>
<section class="card review"><div class="btn-row"><h2>Active recall</h2><button id="begin-review" data-lock>Refresh due cards</button></div>
<p id="review-empty" class="small" hidden>No words are due in the current category and filters. Choose another category or return later.</p><div id="review-content" hidden>
<h2 id="review-word"></h2><p id="review-meta" class="small"></p><button type="button" id="say-word">Hear the word</button>
<form onsubmit="return false"><div class="row"><label for="review-own-words">Explain it in your own words</label><textarea id="review-own-words" maxlength="1500" placeholder="Explain it as if teaching someone new to the word."></textarea></div>
<div class="row"><label for="review-own-example">Use it in a sentence</label><textarea id="review-own-example" maxlength="1500" placeholder="Make a claim about a topic you care about."></textarea></div></form>
<button id="reveal-answer">Reveal meaning</button><div id="review-answer" hidden><p id="review-definition" class="definition"></p><blockquote id="review-example"></blockquote><p id="review-root"></p><p id="review-source" class="word-source"></p></div>
<div id="review-ratings" class="btn-row" hidden><button data-rating="again" data-lock>Again</button><button data-rating="hard" data-lock>Hard</button><button data-rating="good" data-lock>Good</button><button data-rating="easy" data-lock>Easy</button></div></div>
<p class="small">Compare your explanation, then rate your recall honestly. Reviews use a simple Leitner schedule; using a word in debate does not automatically count as remembering it.</p></section>
<section class="card"><details id="word-editor"><summary id="editor-heading">Add a word or edit your notes</summary><form id="word-form"><fieldset data-lock>
<div class="pair"><div class="row"><label for="word">Word</label><input id="word" name="word" type="text" maxlength="80" required></div><div class="row"><label for="part-of-speech">Part of speech</label><input id="part-of-speech" name="part_of_speech" type="text" maxlength="40"></div></div>
<div class="row"><label for="definition">Definition</label><textarea id="definition" name="definition" maxlength="1800" required></textarea></div><div class="row"><label for="example">Example</label><textarea id="example" name="example" maxlength="900"></textarea></div>
<div class="pair"><div class="row"><label for="root">Root / prefix / suffix notes</label><input id="root" name="root" type="text" maxlength="500"></div><div class="row"><label for="family">Related word family</label><input id="family" name="family" type="text" maxlength="500"></div></div>
<div class="pair"><div class="row"><label for="theme">Theme</label><input id="theme" name="theme" type="text" maxlength="80" placeholder="Evidence, policy, listening…"></div><div class="row"><label for="level">Level</label><select id="level" name="level"><option>Essential</option><option>Intermediate</option><option>Advanced</option></select></div></div>
<div class="row"><label for="own-words">Your explanation</label><textarea id="own-words" name="own_words" maxlength="1500"></textarea></div><div class="row"><label for="own-example">Your sentence</label><textarea id="own-example" name="own_example" maxlength="1500"></textarea></div>
<div class="row"><label for="word-context">Where you encountered it / your notes</label><textarea id="word-context" name="context" maxlength="2000" placeholder="Book, article, podcast, audiobook or debate…"></textarea></div>
<div class="pair"><div class="row"><label for="source-title">Reading or listening source</label><input id="source-title" name="source_title" type="text" maxlength="200"></div><div class="row"><label for="source-url">Source link</label><input id="source-url" name="source_url" type="text" maxlength="1000" placeholder="https://…"></div></div>
<label class="check"><input id="focus-word" name="focus" type="checkbox"> Practice this word in debates</label><p id="word-attribution" class="word-source"></p><button type="submit">Save word</button></fieldset></form></details></section>
<section class="card"><h2>Your learning routine</h2><ol class="resource-list">
<li><strong>Roots and families.</strong> Use Word Power Made Easy and Merriam-Webster’s Vocabulary Builder alongside the root and family fields. Add connections in your own words.</li>
<li><strong>Themes and levels.</strong> Use the practical approach you liked in Chris Lele’s workbook and Magoosh: learn a small set around one subject, then use it.</li>
<li><strong>Recall over rereading.</strong> Explain a hidden definition, reveal it, and rate your recall. Export your cards to Anki if you prefer its scheduler.</li>
<li><strong>Listen and collect.</strong> Log words from A Way with Words, nonfiction audiobooks, library listening, and publications you read. Save the source and your own example.</li>
<li><strong>Meaning in context.</strong> Choose the appropriate dictionary sense, notice its nuance, and select it for debate practice.</li>
<li><strong>Explain simply.</strong> Teach the word back in everyday language before trying a more technical sentence.</li></ol>
<p class="small">These are independent exercises inspired by your reading list. Book chapters, commercial word decks and podcast transcripts are not included.</p></section>
<section class="card"><h2>Listen, map, then respond</h2><p>In debate practice, the coach can summarize the opponent’s strongest point and distinguish a factual disagreement, a value judgment, and a policy choice.</p>
<p>Bo Seo’s <a href="https://bigthink.com/series/the-big-think-interview/debate-framework/">RISA framework</a> asks whether a disagreement is real, important, specific and aligned in purpose. Use that check before choosing your rebuttal.</p>
<p>Our separate argument exercise is <strong>State → Support → Explain → Conclude</strong>. Make your point, offer support you actually have, connect it to the claim, and explain why it matters.</p><a href="/practice">Take your focus words into a debate →</a></section>
</div></main>
"""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Vocabulary · LexGlasses</title><style>{css}{VOCAB_CSS}</style></head>'
            f'<body><div class="container"><header class="header"><div><h1>Vocabulary builder</h1>'
            f'<div class="badge">Learn it. Explain it. Use it.</div></div>{nav}</header>'
            f'{body}'
            f'<footer>DISCLAIMER: study notes for your own preparation; '
            f'verify everything against the record. Not legal advice.</footer>'
            f'</div><script>{VOCAB_JS}</script></body></html>')
