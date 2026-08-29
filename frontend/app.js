const app = document.querySelector('#app');
let currentCourse = null;
let study = null;

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) throw new Error((await response.json()).detail || 'Something went wrong.');
  return response.json();
}
const esc = (value) => String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const initials = (card) => `${card.first_name[0] || ''}${card.last_name[0] || ''}`.toUpperCase();
const courseLink = (course) => `#/course/${course.id}`;
const portrait = (card) => card.image_path ? `<img class="avatar portrait" src="/assets/${encodeURI(card.image_path)}" alt="Portrait of ${esc(card.first_name)} ${esc(card.last_name)}">` : `<div class="avatar">${initials(card)}</div>`;

function setView(html) { app.innerHTML = html; }
function notice(message) { return `<p class="notice">${esc(message)}</p>`; }

async function home() {
  setView(document.querySelector('#loading').innerHTML);
  const [courses, pdfs] = await Promise.all([api('/courses'), api('/imports/available')]);
  setView(`
    <section class="hero"><div class="eyebrow">Your local study space</div><h1>Learn the room<br>before you walk in.</h1><p>Import a course PDF, review the people it finds, and build familiarity through short, adaptive sessions.</p></section>
    <section class="section-head"><div><div class="eyebrow">Courses</div><h1>Your courses</h1></div><p>${courses.length ? `${courses.length} imported` : 'Nothing imported yet'}</p></section>
    ${courses.length ? `<div class="course-grid">${courses.map(course => `<a class="course" href="${courseLink(course)}"><div class="mark">${course.card_count}</div><h2>${esc(course.title)}</h2><p>${course.card_count} approved ${course.card_count === 1 ? 'card' : 'cards'} · ${course.last_studied_at ? 'studied before' : 'not studied yet'}</p></a>`).join('')}</div>` : `<div class="empty"><h2>Your first course starts with a PDF.</h2><p>Source files remain on this machine. Imported information is saved in the local app database.</p></div>`}
    <section class="importer" style="margin-top:28px"><div class="eyebrow">Local import</div><h2>Import from <code>data/</code></h2><p class="fine">The importer extracts only high-confidence name lines first. You approve its candidates before they are included in study sessions.</p><div class="import-list">${pdfs.length ? pdfs.map(pdf => `<button class="chip" data-import="${esc(pdf.filename)}">Import ${esc(pdf.filename)}</button>`).join('') : '<span class="fine">No PDFs found in the mounted data directory.</span>'}</div><div id="import-message"></div></section>`);
  document.querySelectorAll('[data-import]').forEach(button => button.addEventListener('click', async () => {
    const message = document.querySelector('#import-message'); button.disabled = true; button.textContent = 'Importing…';
    try { const result = await api('/imports', {method:'POST', body:JSON.stringify({filename:button.dataset.import})}); message.innerHTML = notice(result.status === 'already_imported' ? 'That exact PDF was already imported.' : `Imported ${result.cards} candidate cards from ${result.pages} pages. Review the candidates next.`); if (result.warning) message.innerHTML += notice(result.warning); setTimeout(home, 1100); } catch (error) { message.innerHTML = notice(error.message); button.disabled = false; button.textContent = `Import ${button.dataset.import}`; }
  }));
}

async function courseView(courseId) {
  const [course, cards, candidates, stats] = await Promise.all([api(`/courses/${courseId}`), api(`/courses/${courseId}/cards?sort=first`), api(`/courses/${courseId}/candidates`), api(`/courses/${courseId}/stats`)]);
  currentCourse = course;
  const accuracy = stats.reviews ? Math.round(stats.right_count / stats.reviews * 100) : 0;
  setView(`<a class="back" href="#/">← All courses</a><section class="section-head" style="margin-top:25px"><div><div class="eyebrow">${esc(course.source_filename)}</div><h1>${esc(course.title)}</h1><p>${cards.length} approved cards · ${candidates.length} waiting for review</p></div><div class="actions"><button class="button secondary" id="review-candidates">Review imports</button><button class="button secondary" id="add-card">Add person</button><button class="button" id="start-study">Start session</button></div></section><section class="stats" aria-label="Course statistics"><article class="stat panel"><strong>${stats.session_count}</strong><span>sessions</span></article><article class="stat panel"><strong>${stats.reviews}</strong><span>answers</span></article><article class="stat panel"><strong>${accuracy}%</strong><span>accuracy</span></article><article class="stat panel"><strong>${stats.wrong_count}</strong><span>misses</span></article></section><div class="toolbar"><input class="search" id="search" placeholder="Search people" aria-label="Search people"><select class="select" id="sort" aria-label="Sort roster"><option value="first">First name</option><option value="last">Last name</option><option value="confidence">Confidence (low first)</option></select></div><div id="roster"></div>`);
  const roster = document.querySelector('#roster');
  function renderRoster(items) { roster.innerHTML = items.length ? `<div class="roster">${items.map(card => `<article class="person panel">${portrait(card)}<h2>${esc(card.first_name)} ${esc(card.last_name)}</h2><div class="fine">${card.seen_count ? `${card.right_count}/${card.seen_count} correct` : 'New to you'}</div><span class="tag">recall strength ${Math.round(card.mastery * 100)}%</span></article>`).join('')}</div>` : `<div class="empty"><h2>No approved cards yet.</h2><p>Review the imported candidates, or add cards after your first successful PDF import.</p></div>`; }
  renderRoster(cards);
  document.querySelector('#search').addEventListener('input', event => { const query = event.target.value.toLowerCase(); renderRoster(cards.filter(card => `${card.first_name} ${card.last_name}`.toLowerCase().includes(query))); });
  document.querySelector('#sort').addEventListener('change', async event => { const sorted = await api(`/courses/${courseId}/cards?sort=${event.target.value}`); cards.splice(0, cards.length, ...sorted); renderRoster(cards); });
  document.querySelector('#start-study').addEventListener('click', () => setupView(course, cards.length));
  document.querySelector('#review-candidates').addEventListener('click', () => { location.hash = `#/course/${course.id}/review`; });
  document.querySelector('#add-card').addEventListener('click', () => { location.hash = `#/course/${course.id}/add`; });
}

function candidateView(course, candidates) {
  setView(`<a class="back" href="${courseLink(course)}">← ${esc(course.title)}</a><section class="setup"><div class="eyebrow">Import review</div><h1>${candidates.length ? 'Approve people the importer found.' : 'No candidates waiting.'}</h1><p class="fine">Only approved entries appear in sessions. The initial parser intentionally stays cautious.</p>${candidates.length ? `<div class="roster">${candidates.map(card => `<article class="person panel">${portrait(card)}<h2>${esc(card.first_name)} ${esc(card.last_name)}</h2><button class="button secondary" data-approve="${card.id}">Approve</button></article>`).join('')}</div>` : ''}</section>`);
  document.querySelectorAll('[data-approve]').forEach(button => button.addEventListener('click', async () => { button.disabled = true; await api(`/courses/${course.id}/candidates/${button.dataset.approve}/approve`, {method:'POST'}); candidateView(course, await api(`/courses/${course.id}/candidates`)); }));
}

function manualCardView(course) {
  setView(`<a class="back" href="${courseLink(course)}">← ${esc(course.title)}</a><section class="setup"><div class="eyebrow">Manual card</div><h1>Add a person.</h1><p class="fine">Use this for names the cautious PDF importer did not find, or to improve a course gradually.</p><form id="card-form" class="form"><div class="two"><input name="first" required placeholder="First name" aria-label="First name"><input name="last" required placeholder="Last name" aria-label="Last name"></div><textarea name="facts" rows="4" placeholder="Optional facts — one per line" aria-label="Optional facts"></textarea><div class="actions"><button class="button" type="submit">Save person</button></div><div id="form-notice"></div></form></section>`);
  document.querySelector('#card-form').addEventListener('submit', async event => { event.preventDefault(); const form = new FormData(event.currentTarget); const facts = form.get('facts').split('\n').map(item => item.trim()).filter(Boolean); try { await api(`/courses/${course.id}/cards`, {method:'POST', body:JSON.stringify({first_name:form.get('first'),last_name:form.get('last'),facts})}); courseView(course.id); } catch(error) { document.querySelector('#form-notice').innerHTML = notice(error.message); } });
}

function setupView(course, count) {
  let mode = 'adaptive';
  setView(`<a class="back" href="${courseLink(course)}" id="setup-back">← ${esc(course.title)}</a><section class="setup"><div class="eyebrow">Study setup</div><h1>What feels useful today?</h1><p class="fine">Every card is available whenever you are. Adaptive review simply makes a varied, helpful choice.</p><div class="mode-grid"><button class="mode selected" data-mode="adaptive"><h2>Adaptive review</h2><p>Prioritizes people with the lowest predicted recall.</p></button><button class="mode" data-mode="morris"><h2>Expanding recall</h2><p>Repeats a focused base set inside one capped session with widening gaps.</p></button><button class="mode" data-mode="all"><h2>All cards</h2><p>See every approved person once, in a fresh random order.</p></button></div><label class="range" id="base-size">${mode === 'morris' ? 'Base people' : 'Adaptive session length'}: <strong id="length-label">15</strong><input id="length" type="range" min="5" max="${Math.max(5, Math.min(50, count))}" value="${Math.min(15,count)}"></label><div class="actions"><button class="button" id="begin">Begin studying</button></div><div id="setup-notice"></div></section>`);
  document.querySelector('#setup-back').addEventListener('click', event => { event.preventDefault(); courseView(course.id); });
  document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => { mode = button.dataset.mode; document.querySelectorAll('[data-mode]').forEach(item => item.classList.toggle('selected', item === button)); document.querySelector('.range').classList.toggle('hidden', mode === 'all'); document.querySelector('#base-size').firstChild.textContent = mode === 'morris' ? 'Base people: ' : 'Adaptive session length: '; const input = document.querySelector('#length'); input.max = mode === 'morris' ? Math.max(5, Math.min(15, count)) : Math.max(5, Math.min(50, count)); if (+input.value > +input.max) { input.value = input.max; document.querySelector('#length-label').textContent = input.value; } }));
  document.querySelector('#length').addEventListener('input', e => document.querySelector('#length-label').textContent = e.target.value);
  document.querySelector('#begin').addEventListener('click', async () => { try { const result = await api(`/courses/${course.id}/sessions`, {method:'POST', body:JSON.stringify({mode,limit:+document.querySelector('#length').value})}); study = {...result, index:0, revealed:false}; if (mode === 'morris') { study = {...study, remaining:[...result.cards], pending:[], current:null, stages:{}, reviews:0, maxReviews:Math.min(60, Math.max(15, result.cards.length * 5))}; advanceMorris(); } studyView(); } catch(error) { document.querySelector('#setup-notice').innerHTML = notice(error.message); } });
}

function advanceMorris() {
  const due = study.pending.findIndex(item => item.readyAt <= study.reviews);
  if (due >= 0) study.current = study.pending.splice(due, 1)[0].card;
  else if (study.remaining.length) study.current = study.remaining.shift();
  else if (study.pending.length) study.current = study.pending.sort((a, b) => a.readyAt - b.readyAt).shift().card;
  else study.current = null;
}

function studyView() {
  const card = study.mode === 'morris' ? study.current : study.cards[study.index];
  if (!card) return completeStudy();
  const complete = study.mode === 'morris' ? Math.round((study.reviews / study.maxReviews) * 100) : Math.round((study.index / study.cards.length) * 100);
  const sessionTitle = study.mode === 'all' ? 'All cards' : study.mode === 'morris' ? 'Expanding recall' : 'Adaptive review';
  const position = study.mode === 'morris' ? `${study.reviews + 1} / up to ${study.maxReviews}` : `${study.index + 1} / ${study.cards.length}`;
  setView(`<div class="study-wrap"><div class="session-meta"><span>${sessionTitle}</span><span>${position}</span></div><div class="study-card" id="flashcard" role="button" tabindex="0" aria-label="Flip card">${portrait(card)}${study.revealed ? `<div class="answer"><div class="eyebrow">The answer</div><div class="name">${esc(card.first_name)} ${esc(card.last_name)}</div>${card.facts.length ? `<ul>${card.facts.map(fact=>`<li>${esc(fact)}</li>`).join('')}</ul>` : ''}</div>` : `<div><div class="eyebrow">Who is this?</div><h1>Can you name them?</h1><p>Flip when you have an answer in mind.</p></div>`}</div><div class="study-actions">${study.revealed ? `<button class="button danger" id="wrong">Wrong <span class="key">W</span></button><button class="button" id="right">Right <span class="key">R</span></button>` : `<button class="button secondary" id="flip">Flip card <span class="key">Space</span></button><button class="button" id="right">Right <span class="key">R</span></button>`}</div><div class="fine" style="margin-top:18px">${complete}% complete · <span class="key">Esc</span> to end session</div></div>`);
  const reveal = () => { if (!study.revealed) { study.revealed = true; studyView(); } };
  document.querySelector('#flashcard').addEventListener('click', reveal); document.querySelector('#flashcard').addEventListener('keydown', event => { if(event.key === 'Enter' || event.key === ' ') { event.preventDefault(); reveal(); } });
  document.querySelector('#flip')?.addEventListener('click', reveal);
  document.querySelector('#right')?.addEventListener('click', () => score('right'));
  document.querySelector('#wrong')?.addEventListener('click', () => score('wrong'));
}

async function score(result) { const card = study.mode === 'morris' ? study.current : study.cards[study.index]; await api(`/sessions/${study.id}/reviews`, {method:'POST',body:JSON.stringify({card_id:card.id,result})}); if (study.mode === 'morris') { study.reviews += 1; const stage = result === 'right' ? (study.stages[card.id] || 0) + 1 : 0; study.stages[card.id] = stage; if (result === 'wrong' || stage < 3) study.pending.push({card, readyAt:study.reviews + (result === 'wrong' ? 2 : stage === 1 ? 3 : 7)}); if (study.reviews >= study.maxReviews) return completeStudy(); advanceMorris(); if (!study.current) return completeStudy(); } else study.index += 1; study.revealed = false; studyView(); }
async function completeStudy() { const result = await api(`/sessions/${study.id}/complete`, {method:'POST'}); const accuracy = result.reviewed_count ? Math.round(result.right_count / result.reviewed_count * 100) : 0; setView(`<section class="setup"><div class="eyebrow">Session complete</div><h1>${accuracy}% correct.</h1><p class="fine">You reviewed ${result.reviewed_count} people: ${result.right_count} right and ${result.wrong_count} wrong. Your next adaptive session will adjust from what you just learned.</p><div class="actions"><a class="button" id="complete-back" href="${courseLink(currentCourse)}">Back to course</a></div></section>`); study = null; document.querySelector('#complete-back').addEventListener('click', event => { event.preventDefault(); courseView(currentCourse.id); }); }

document.addEventListener('keydown', event => { if (!study || ['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)) return; if ((event.key === ' ' || event.key === 'Enter') && !study.revealed) { event.preventDefault(); study.revealed = true; studyView(); } if (event.key.toLowerCase() === 'r') score('right'); if (study.revealed && event.key.toLowerCase() === 'w') score('wrong'); if (event.key === 'Escape') completeStudy(); });
window.addEventListener('hashchange', route);
async function route() {
  const match = location.hash.match(/^#\/course\/([^/]+)(?:\/(review|add))?$/);
  if (!match) return home();
  const [, courseId, child] = match;
  if (!child) return courseView(courseId);
  try {
    const course = await api(`/courses/${courseId}`);
    if (child === 'review') return candidateView(course, await api(`/courses/${courseId}/candidates`));
    return manualCardView(course);
  } catch (error) {
    setView(`<section class="empty"><h2>That course is unavailable.</h2><p>${esc(error.message)}</p><a class="button" href="#/">Back to courses</a></section>`);
  }
}
route();
