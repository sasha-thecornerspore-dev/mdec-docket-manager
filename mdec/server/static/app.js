/* MDEC Docket Manager — UI logic. No framework, no build step. */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = { status: null, features: null, entries: [], docs: [],
                settings: null, secrets: {} };
let lastSeenSeq = Number(localStorage.getItem('mdec.lastSeenSeq') || 0);

/* --- helpers ----------------------------------------------------------- */

async function api(path, opts = {}) {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json' }, ...opts,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
  if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
  return data;
}

let toastTimer;
function toast(msg, bad = false) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.toggle('is-bad', bad);
  el.classList.add('is-up');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('is-up'), 6000);
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** Minimal markdown: headings, bullets, bold, code. Escapes first. */
function md(s) {
  const lines = esc(s ?? '').split('\n');
  let out = '', inList = false;
  for (let line of lines) {
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      if (!inList) { out += '<ul>'; inList = true; }
      out += `<li>${inline(bullet[1])}</li>`;
      continue;
    }
    if (inList) { out += '</ul>'; inList = false; }
    const head = line.match(/^(#{1,4})\s+(.*)$/);
    if (head) { out += `<h3>${inline(head[2])}</h3>`; continue; }
    out += line.trim() ? `<p>${inline(line)}</p>` : '';
  }
  if (inList) out += '</ul>';
  return out;
  function inline(t) {
    return t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/`(.+?)`/g, '<code>$1</code>');
  }
}

const fmtSize = b => !b ? '—'
  : b < 1024 ? b + ' B'
  : b < 1048576 ? (b / 1024).toFixed(0) + ' KB'
  : (b / 1048576).toFixed(1) + ' MB';

const fmtTime = iso => {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString([], {
    month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

const seq4 = n => String(n ?? 0).padStart(4, '0');

/* --- tabs -------------------------------------------------------------- */

$$('.tab').forEach(tab => tab.addEventListener('click', () => {
  $$('.tab').forEach(t => t.classList.toggle('is-active', t === tab));
  $$('.panel').forEach(p =>
    p.classList.toggle('is-active', p.id === 'panel-' + tab.dataset.tab));
  loadTab(tab.dataset.tab);
}));

function loadTab(name) {
  if (name === 'docket')    renderDocket();
  if (name === 'documents') renderDocuments();
  if (name === 'notes')     loadNotes();
  if (name === 'analysis')  loadAnalyses();
  if (name === 'activity')  loadRuns();
  if (name === 'settings')  { loadSettings(); loadCases(); }
}

/* --- theme ------------------------------------------------------------- */

const savedTheme = localStorage.getItem('mdec.theme');
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
$('#btnTheme').addEventListener('click', () => {
  const cur = document.documentElement.dataset.theme;
  const dark = cur === 'dark' ||
    (cur !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  const next = dark ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('mdec.theme', next);
});

/* --- status / dashboard ------------------------------------------------ */

async function loadStatus() {
  try { state.status = await api('/status'); }
  catch (e) { toast('Could not read status: ' + e.message, true); return; }
  const s = state.status;

  $('#caseCaption').textContent = s.case.caption || s.case.case_number ||
    'MDEC Docket Manager';
  $('#caseNumber').textContent = s.case.case_number || 'No case yet';
  $('#caseCourt').textContent = s.case.court || '';

  // case switcher
  const sw = $('#caseSwitch');
  sw.innerHTML = (s.cases || []).map(c =>
    `<option value="${c.id}">${esc(c.case_number)}${
      c.caption ? ' — ' + esc(c.caption.slice(0, 40)) : ''}</option>`).join('') ||
    '<option value="">No cases — add one in Settings</option>';
  if (s.case.id) sw.value = String(s.case.id);
  sw.disabled = !(s.cases || []).length;

  $('#dashFolder').textContent = s.case_folder || '—';
  const fs = $('#dashFolderState');
  fs.textContent = s.case_folder
    ? (s.case_folder_exists ? 'exists' : 'not created yet') : '';
  fs.className = 'chip ' + (s.case_folder_exists ? 'ok' : 'warn');
  const st = $('#monitorState');
  st.textContent = s.monitor.message || 'idle';
  st.title = s.monitor.message || 'idle';
  st.classList.toggle('is-busy', !!s.monitor.busy);
  $('#btnCheck').disabled = !!s.monitor.busy;

  const c = s.counts;
  const cells = [
    ['Docket entries', c.entries, false], ['Documents', c.documents, false],
    ['Awaiting download', c.missing, c.missing > 0],
    ['OCR done', c.ocr_done, false], ['Sent to RAG', c.rag_exported, false],
    ['Notes', c.notes, false], ['Analyses', c.analyses, false],
  ];
  $('#tally').innerHTML = cells.map(([k, n, alert]) => `
    <div class="tally-cell ${alert ? 'is-alert' : ''}">
      <span class="tally-n">${n}</span>
      <span class="tally-k">${k}</span></div>`).join('');

  $('#dashRuns').innerHTML = s.runs.length
    ? s.runs.map(runRow).join('') : '<p class="empty">No checks have run yet.</p>';

  renderChecklist();
}

/** Feature readiness arrives separately — detecting it is slow on a cold start,
 *  and the dashboard shouldn't wait on it to paint. */
async function loadFeatures() {
  try { state.features = await api('/features'); }
  catch { return; }
  renderChecklist();
  const f = state.features;
  // The packaged build ships without the browser binaries; offer the download.
  $('#btnInstallBrowser').hidden = !!f.browser_installed;
  const ocrEl = $('#ocrState'), anEl = $('#analysisState');
  if (ocrEl) ocrEl.textContent = f.ocr_available
    ? 'OCR tools found (Tesseract + Ghostscript).' : f.ocr_why;
  if (anEl) anEl.textContent = f.analysis_backend === 'none'
    ? f.analysis_why : `Using the ${f.analysis_backend === 'cli'
      ? 'Claude subscription via the Claude Code CLI' : 'Anthropic API'}.`;
}

function renderChecklist() {
  const s = state.status;
  if (!s) return;
  const f = state.features;
  const rows = [
    [!!s.case.case_number, 'Case added',
      'Add a case in Settings → Cases.'],
  ];
  if (f) rows.push(
    [f.browser_installed, 'Browser installed',
      'The private browser this app drives is not downloaded yet — use ' +
      '"Download browser" below (~130 MB, once).'],
  );
  rows.push(
    [s.portal_state === 'ready',
      'Signed in — docket visible',
      s.portal_state === 'captcha'
        ? 'The portal is showing a bot-detection challenge. Open the portal ' +
          'window and complete it yourself — the app will not answer it for you.'
        : s.portal_state === 'signed_out'
        ? 'Not signed in. Click "Open portal window", sign in, and confirm you ' +
          'can see your case — checks find nothing until then.'
        : s.portal_state === 'empty'
        ? 'Signed in, but that case number shows no docket. Check it matches ' +
          'the docket exactly.'
        : 'Click "Open portal window" to sign in and confirm the docket loads.'],
    [s.schedule.enabled, `Scheduled checks at ${s.schedule.times.join(', ')}`,
      'Scheduled checks are off.'],
  );
  if (f) rows.push(
    [f.analysis_enabled && f.analysis_backend !== 'none',
      `Claude analysis (${f.analysis_backend})`,
      f.analysis_why || 'Turn on analysis in Settings.'],
    [f.ocr_enabled && f.ocr_available, 'OCR ready',
      f.ocr_enabled ? f.ocr_why : 'OCR is off. Turn it on in Settings.'],
    [f.rag_targets.length > 0, `RAG export → ${f.rag_targets.join(', ') || 'none'}`,
      'No RAG target configured.'],
  );
  $('#dashChecks').innerHTML = rows.map(([ok, good, bad]) => `
    <li><span class="mark ${ok ? 'ok' : 'no'}">${ok ? '✓' : '!'}</span>
      <span>${esc(ok ? good : bad)}</span></li>`).join('') +
    (f ? '' : '<li><span class="mark">…</span><span>Checking OCR and ' +
              'analysis availability…</span></li>');
}

function runRow(r) {
  return `<div class="run">
    <span class="run-status ${r.status}">${esc(r.status)}</span>
    <span>${esc(r.kind)} — ${r.new_entries} new ${
      r.new_entries === 1 ? 'entry' : 'entries'}, ${r.new_documents} ${
      r.new_documents === 1 ? 'document' : 'documents'}</span>
    <span>${fmtTime(r.started_at)}</span>
    ${r.log ? `<pre class="run-log">${esc(r.log)}</pre>` : ''}
  </div>`;
}

/* --- docket ------------------------------------------------------------ */

async function loadEntries() {
  try {
    const d = await api('/entries');
    state.entries = d.entries;
    const maxSeq = state.entries.reduce((m, e) => Math.max(m, e.seq), 0);
    if (maxSeq > lastSeenSeq) {
      // Keep the mark until the user actually opens the Docket tab.
      state.newSince = lastSeenSeq;
    }
  } catch { state.entries = []; }
}

function entryHTML(e) {
  const isNew = e.seq > (state.newSince ?? lastSeenSeq);
  const docs = e.documents || [];
  return `<article class="entry ${isNew ? 'is-new' : ''}" data-id="${e.id}">
    <div class="entry-seq">${seq4(e.seq)}</div>
    <div class="entry-main">
      <div class="entry-head" tabindex="0" role="button"
           aria-expanded="false">
        <span class="entry-date">${esc(e.file_date || '—')}</span>
        <span class="entry-name">${esc(e.name || 'Untitled entry')}</span>
        ${isNew ? '<span class="stamp">New</span>' : ''}
        <span class="chips">
          ${docs.length ? `<span class="chip ok">${docs.length} file${
            docs.length === 1 ? '' : 's'}</span>`
            : e.has_documents ? '<span class="chip warn">no file</span>' : ''}
          ${e.note_count ? `<span class="chip">${e.note_count} note${
            e.note_count === 1 ? '' : 's'}</span>` : ''}
          ${e.analysis_count ? '<span class="chip ok">analyzed</span>' : ''}
        </span>
      </div>
      ${e.comment ? `<p class="entry-comment">${esc(e.comment)}</p>` : ''}
      <div class="entry-body">
        ${e.section ? `<div class="chip">${esc(e.section)}</div>` : ''}
        ${docs.length ? `<div class="subhead">Documents</div>` +
          docs.map(d => `<div class="doc-line">
            <a href="/api/documents/${d.id}/file" target="_blank"
               rel="noopener">${esc(d.filename)}</a>
            <span class="chip">${fmtSize(d.size_bytes)}</span>
            ${d.ocr_done ? '<span class="chip ok">ocr</span>' : ''}
            ${d.rag_exported ? '<span class="chip ok">rag</span>' : ''}
          </div>`).join('') : ''}
        <div class="entry-detail" data-detail="${e.id}"></div>
        <div class="entry-tools">
          <button class="btn-mini" data-act="analyze" data-id="${e.id}"
            ${docs.length ? '' : 'disabled'}>Analyze this entry</button>
          <button class="btn-mini" data-act="note" data-id="${e.id}">Add note</button>
        </div>
      </div>
    </div>
  </article>`;
}

function renderDocket() {
  const q = ($('#docketFilter').value || '').toLowerCase();
  const onlyDocs = $('#docketOnlyDocs').checked;
  let rows = state.entries;
  if (onlyDocs) rows = rows.filter(e => (e.documents || []).length);
  if (q) rows = rows.filter(e =>
    (e.name + ' ' + e.comment + ' ' + e.file_date).toLowerCase().includes(q));
  rows = [...rows].sort((a, b) => b.seq - a.seq);   // newest filing first
  $('#docketList').innerHTML = rows.length ? rows.map(entryHTML).join('')
    : '<p class="empty">Nothing on the docket yet. Run a check.</p>';

  // Opening the tab acknowledges what's new.
  const maxSeq = state.entries.reduce((m, e) => Math.max(m, e.seq), 0);
  if (maxSeq > lastSeenSeq) {
    lastSeenSeq = maxSeq;
    localStorage.setItem('mdec.lastSeenSeq', String(maxSeq));
  }
}

$('#docketFilter').addEventListener('input', renderDocket);
$('#docketOnlyDocs').addEventListener('change', renderDocket);

$('#docketList').addEventListener('click', async ev => {
  const head = ev.target.closest('.entry-head');
  if (head) {
    const entry = head.closest('.entry');
    const open = entry.classList.toggle('is-open');
    head.setAttribute('aria-expanded', String(open));
    if (open) loadEntryDetail(entry.dataset.id);
    return;
  }
  const btn = ev.target.closest('[data-act]');
  if (!btn) return;
  const id = btn.dataset.id;
  if (btn.dataset.act === 'analyze') {
    btn.disabled = true;
    btn.textContent = 'Analyzing…';
    try {
      const r = await api(`/actions/analyze-entry/${id}`, { method: 'POST' });
      toast(r.message, !r.ok);
      await refreshAll();
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = 'Analyze this entry'; }
  }
  if (btn.dataset.act === 'note') {
    $$('.tab').find(t => t.dataset.tab === 'notes').click();
    $('#noteEntry').value = id;
    $('#noteBody').focus();
  }
});

async function loadEntryDetail(id) {
  const box = $(`[data-detail="${id}"]`);
  if (!box || box.dataset.loaded) return;
  box.dataset.loaded = '1';
  try {
    const [n, a] = await Promise.all([
      api('/notes?entry_id=' + id), api('/analyses?entry_id=' + id)]);
    box.innerHTML =
      (a.analyses.length ? '<div class="subhead">Analysis</div>' +
        a.analyses.map(analysisHTML).join('') : '') +
      (n.notes.length ? '<div class="subhead">Notes</div>' +
        n.notes.map(noteHTML).join('') : '');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

/* --- documents --------------------------------------------------------- */

async function loadDocs() {
  try { state.docs = (await api('/documents')).documents; }
  catch { state.docs = []; }
}

function renderDocuments() {
  const q = ($('#docFilter').value || '').toLowerCase();
  const rows = state.docs.filter(d =>
    !q || (d.filename + ' ' + d.title).toLowerCase().includes(q));
  $('#docTable tbody').innerHTML = rows.length ? rows.map(d => `<tr>
    <td class="num">${seq4(d.seq)}</td>
    <td>${esc(d.file_date || '—')}</td>
    <td class="wrap">${esc(d.title || d.entry_name)}</td>
    <td class="wrap">${esc(d.filename)}</td>
    <td class="num">${fmtSize(d.size_bytes)}</td>
    <td>${d.ocr_done ? '<span class="chip ok">yes</span>' : '—'}</td>
    <td>${d.rag_exported ? '<span class="chip ok">yes</span>' : '—'}</td>
    <td><a href="/api/documents/${d.id}/file" target="_blank"
           rel="noopener">PDF</a></td>
  </tr>`).join('')
    : '<tr><td colspan="8"><p class="empty">No documents yet.</p></td></tr>';
}

$('#docFilter').addEventListener('input', renderDocuments);

/* --- notes ------------------------------------------------------------- */

function noteHTML(n) {
  return `<div class="note" data-note="${n.id}">
    <div class="note-meta">
      <span>${fmtTime(n.created_at)}</span>
      ${n.seq != null ? `<span>entry ${seq4(n.seq)}</span>` : '<span>case note</span>'}
      ${n.entry_name ? `<span>${esc(n.entry_name)}</span>` : ''}
      <button class="btn-mini" data-note-del="${n.id}">Delete</button>
    </div>
    <div class="note-body">${md(n.body)}</div>
  </div>`;
}

async function loadNotes() {
  fillEntrySelect();
  try {
    const d = await api('/notes');
    $('#noteList').innerHTML = d.notes.length ? d.notes.map(noteHTML).join('')
      : '<p class="empty">No notes yet.</p>';
  } catch (e) { $('#noteList').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

function fillEntrySelect() {
  const sel = $('#noteEntry');
  const cur = sel.value;
  sel.innerHTML = '<option value="">Case-level note (no entry)</option>' +
    [...state.entries].sort((a, b) => b.seq - a.seq).map(e =>
      `<option value="${e.id}">${seq4(e.seq)} — ${esc(
        (e.name || 'Untitled').slice(0, 70))}</option>`).join('');
  if (cur) sel.value = cur;
}

$('#btnAddNote').addEventListener('click', async () => {
  const body = $('#noteBody').value.trim();
  if (!body) { toast('Write something first.', true); return; }
  const entry_id = $('#noteEntry').value ? Number($('#noteEntry').value) : null;
  try {
    await api('/notes', { method: 'POST', body: JSON.stringify({ body, entry_id }) });
    $('#noteBody').value = '';
    toast('Note saved.');
    await refreshAll();
    loadNotes();
  } catch (e) { toast(e.message, true); }
});

document.addEventListener('click', async ev => {
  const del = ev.target.closest('[data-note-del]');
  if (!del) return;
  try {
    await api('/notes/' + del.dataset.noteDel, { method: 'DELETE' });
    toast('Note deleted.');
    loadNotes();
    await refreshAll();
  } catch (e) { toast(e.message, true); }
});

/* --- analyses ---------------------------------------------------------- */

function analysisHTML(a) {
  const dl = (a.deadlines || []).filter(d => d && (d.date || d.description));
  return `<div class="note analysis">
    <div class="note-meta">
      <span>${fmtTime(a.created_at)}</span>
      <span>${esc(a.kind === 'case' ? 'case briefing' : 'filing')}</span>
      ${a.seq != null ? `<span>entry ${seq4(a.seq)}</span>` : ''}
      <span>${esc(a.model)}</span>
    </div>
    <div class="note-body">${md(a.summary)}</div>
    ${dl.length ? `<ul class="deadlines">${dl.map(d => `<li>
      <span class="d-date">${esc(d.date || 'date unclear')}</span>
      <span>${esc(d.description || '')}</span></li>`).join('')}</ul>` : ''}
    ${a.recommendations ? `<div class="subhead">Suggested next steps</div>
      <div class="note-body">${md(a.recommendations)}</div>` : ''}
  </div>`;
}

async function loadAnalyses() {
  try {
    const d = await api('/analyses');
    $('#analysisList').innerHTML = d.analyses.length
      ? d.analyses.map(analysisHTML).join('')
      : '<p class="empty">No analyses yet. Turn on analysis in Settings, then ' +
        'analyze an entry or write a case briefing.</p>';
  } catch (e) {
    $('#analysisList').innerHTML = `<p class="empty">${esc(e.message)}</p>`;
  }
}

async function analyzeCase(btn) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = 'Writing…';
  try {
    const r = await api('/actions/analyze-case', { method: 'POST' });
    toast(r.message, !r.ok);
    loadAnalyses();
    await refreshAll();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = label; }
}
$('#btnAnalyzeCase').addEventListener('click', e => analyzeCase(e.target));
$('#btnAnalyzeCase2').addEventListener('click', e => analyzeCase(e.target));

/* --- runs -------------------------------------------------------------- */

async function loadRuns() {
  try {
    const d = await api('/runs?limit=100');
    $('#runList').innerHTML = d.runs.length ? d.runs.map(runRow).join('')
      : '<p class="empty">No activity yet.</p>';
  } catch (e) { $('#runList').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

/* --- settings ---------------------------------------------------------- */

function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
}

async function loadSettings() {
  const d = await api('/settings');
  state.settings = d.settings;
  state.secrets = d.secrets;
  $$('#settingsForm [name]').forEach(el => {
    let v = getPath(d.settings, el.name);
    if (Array.isArray(v)) v = v.join(', ');
    if (el.type === 'checkbox') el.checked = !!v;
    else el.value = v ?? '';
  });
  $$('[data-secret-state]').forEach(el => {
    const name = el.dataset.secretState;
    const set = state.secrets[name];
    const base = el.dataset.baseHint ?? (el.dataset.baseHint = el.textContent.trim());
    el.textContent = (set ? 'Stored in Windows Credential Manager. Type to replace, '
      + 'or clear the field and save to delete. ' : 'Not set. ') + base;
  });
  const f = state.features;
  if (f) {
    $('#ocrState').textContent = f.ocr_available
      ? 'OCR tools found (Tesseract + Ghostscript).' : f.ocr_why;
    $('#analysisState').textContent = f.analysis_backend === 'none'
      ? f.analysis_why : `Using the ${f.analysis_backend === 'cli'
        ? 'Claude subscription via the Claude Code CLI' : 'Anthropic API'}.`;
  } else {
    loadFeatures();
  }
}

$('#settingsForm').addEventListener('submit', async ev => {
  ev.preventDefault();
  const payload = {};
  $$('#settingsForm [name]').forEach(el => {
    const parts = el.name.split('.');
    let cur = payload;
    parts.slice(0, -1).forEach(p => { cur = cur[p] ??= {}; });
    const key = parts.at(-1);
    let v = el.type === 'checkbox' ? el.checked
      : el.type === 'number' ? Number(el.value)
      : el.value;
    if (key === 'times' || key === 'senders') {
      v = String(v).split(',').map(s => s.trim()).filter(Boolean);
    }
    cur[key] = v;
  });
  try {
    await api('/settings', { method: 'POST', body: JSON.stringify(payload) });
    // Secrets go one at a time, and only when the user typed something.
    for (const el of $$('[data-secret]')) {
      if (el.value === '') continue;
      await api('/secrets', { method: 'POST', body: JSON.stringify(
        { name: el.dataset.secret, value: el.value })});
      el.value = '';
    }
    toast('Settings saved.');
    state.features = null;      // toggles may have changed what's available
    await refreshAll();
    await loadFeatures();
    loadSettings();
  } catch (e) { toast(e.message, true); }
});

/* --- cases ------------------------------------------------------------- */

$('#caseSwitch').addEventListener('change', async ev => {
  const id = ev.target.value;
  if (!id) return;
  try {
    await api(`/cases/${id}/activate`, { method: 'POST' });
    // A different case means different entries, documents, notes — reset the
    // "new since" mark so one case's marks don't leak onto another.
    lastSeenSeq = 0;
    localStorage.setItem('mdec.lastSeenSeq', '0');
    await refreshAll();
    loadTab($('.tab.is-active').dataset.tab);
    toast('Switched case.');
  } catch (e) { toast(e.message, true); }
});

async function loadCases() {
  const d = await api('/cases');
  const rows = d.cases.map(c => `
    <div class="case-row ${c.case_number === d.active ? 'is-active' : ''}"
         data-case="${c.id}">
      <div class="case-row-head">
        <span class="case-row-num">${esc(c.case_number)}</span>
        <span class="case-row-caption">${esc(c.caption || '—')}</span>
        <span class="chip">${c.entry_count} entries</span>
        <span class="chip">${c.doc_count} docs</span>
        ${c.case_number === d.active ? '<span class="stamp">Active</span>' : ''}
      </div>
      <div class="case-row-fields">
        <label>Caption <input class="input" data-f="caption"
               value="${esc(c.caption || '')}"></label>
        <label>Court <input class="input" data-f="court"
               value="${esc(c.court || '')}"></label>
        <label>Document folder
          <span class="folder-picker">
            <input class="input" data-f="downloads"
                   value="${esc(c.downloads || c.resolved_folder || '')}">
            <button type="button" class="btn" data-browse-field="${c.id}">Browse…</button>
          </span></label>
        <label class="check"><input type="checkbox" data-f="monitor_enabled"
               ${c.monitor_enabled ? 'checked' : ''}> Include in scheduled checks</label>
      </div>
      <div class="case-row-tools">
        <button type="button" class="btn-mini" data-case-save="${c.id}">Save</button>
        ${c.case_number === d.active ? ''
          : `<button type="button" class="btn-mini" data-case-activate="${c.id}">Make active</button>`}
        <button type="button" class="btn-mini" data-case-del="${c.id}"
                data-num="${esc(c.case_number)}">Stop tracking</button>
      </div>
    </div>`).join('');
  $('#caseList').innerHTML = rows ||
    '<div class="case-row"><p class="empty">No cases yet. Add one below.</p></div>';
}

$('#btnAddCase').addEventListener('click', async () => {
  const payload = {
    case_number: $('#newCaseNumber').value.trim(),
    caption: $('#newCaseCaption').value.trim(),
    court: $('#newCaseCourt').value.trim(),
    downloads: $('#newCaseFolder').value.trim(),
    monitor_enabled: $('#newCaseMonitor').checked,
  };
  if (!payload.case_number) { toast('Enter a case number.', true); return; }
  try {
    const r = await api('/cases', { method: 'POST', body: JSON.stringify(payload) });
    toast(`Added ${payload.case_number}. Documents go to ${r.folder}`);
    ['newCaseNumber', 'newCaseCaption', 'newCaseCourt', 'newCaseFolder']
      .forEach(id => { $('#' + id).value = ''; });
    lastSeenSeq = 0;
    localStorage.setItem('mdec.lastSeenSeq', '0');
    await refreshAll();
    loadCases();
  } catch (e) { toast(e.message, true); }
});

$('#caseList').addEventListener('click', async ev => {
  const row = ev.target.closest('.case-row');
  const save = ev.target.closest('[data-case-save]');
  const act  = ev.target.closest('[data-case-activate]');
  const del  = ev.target.closest('[data-case-del]');
  const browse = ev.target.closest('[data-browse-field]');

  if (browse) {
    const input = row.querySelector('[data-f="downloads"]');
    await pickInto(input);
    return;
  }
  if (save) {
    const get = f => row.querySelector(`[data-f="${f}"]`);
    const payload = {
      case_number: row.querySelector('.case-row-num').textContent.trim(),
      caption: get('caption').value.trim(),
      court: get('court').value.trim(),
      downloads: get('downloads').value.trim(),
      monitor_enabled: get('monitor_enabled').checked,
    };
    try {
      await api(`/cases/${save.dataset.caseSave}`, {
        method: 'PUT', body: JSON.stringify(payload) });
      toast('Case saved.');
      await refreshAll();
      loadCases();
    } catch (e) { toast(e.message, true); }
  }
  if (act) {
    try {
      await api(`/cases/${act.dataset.caseActivate}/activate`, { method: 'POST' });
      lastSeenSeq = 0;
      localStorage.setItem('mdec.lastSeenSeq', '0');
      await refreshAll();
      loadCases();
      toast('Switched case.');
    } catch (e) { toast(e.message, true); }
  }
  if (del) {
    if (!confirm(`Stop tracking ${del.dataset.num}?\n\nThis forgets its docket, ` +
                 `notes, and analyses. Downloaded PDFs are NOT deleted.`)) return;
    try {
      const r = await api(`/cases/${del.dataset.caseDel}`, { method: 'DELETE' });
      toast(r.message);
      await refreshAll();
      loadCases();
    } catch (e) { toast(e.message, true); }
  }
});

/* --- folder picker ----------------------------------------------------- */

async function pickInto(input) {
  try {
    const r = await api('/actions/pick-folder', {
      method: 'POST', body: JSON.stringify({ initial: input.value || '' })});
    if (r.path) input.value = r.path;      // empty path = user cancelled
  } catch (e) { toast(e.message, true); }
}

document.addEventListener('click', async ev => {
  const byId = ev.target.closest('[data-browse]');
  if (byId) { await pickInto($('#' + byId.dataset.browse)); return; }
  const byName = ev.target.closest('[data-browse-name]');
  if (byName) await pickInto($(`[name="${byName.dataset.browseName}"]`));
});

/* --- actions ----------------------------------------------------------- */

$('#btnInstallBrowser').addEventListener('click', async () => {
  const b = $('#btnInstallBrowser');
  if (!confirm('Download the private browser this app drives?\n\n' +
               'About 130 MB, once. It is separate from your everyday browser.')) return;
  b.disabled = true; b.textContent = 'Downloading… (this takes a few minutes)';
  try {
    const r = await api('/actions/install-browser', { method: 'POST' });
    toast(r.message, !r.ok);
    state.features = null;
    await loadFeatures();
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; b.textContent = 'Download browser (~130 MB)'; }
});

$('#btnDiagnose').addEventListener('click', async () => {
  const b = $('#btnDiagnose');
  b.disabled = true; b.textContent = 'Looking at the page…';
  try {
    const r = await api('/actions/diagnose', { method: 'POST' });
    toast(r.message, !r.ok);
    const rep = r.report;
    $('#adoptOut').innerHTML = !rep ? '' : `
      <p class="hint"><strong>${esc(rep.verdict)}</strong></p>
      <div class="r-row"><span>state</span><span>${esc(rep.state)}</span>
        <span>${rep.chars} chars on page</span></div>
      <div class="r-row"><span>doc buttons</span>
        <span>parser finds ${rep.parserWouldFind}</span>
        <span>${rep.buttonCount} buttons total</span></div>
      <div class="r-row"><span>rows</span>
        <span>${rep.rowsWithDates} with dates</span>
        <span>${esc(JSON.stringify(rep.containers))}</span></div>
      ${rep.buttonTexts?.length ? `<p class="hint">Button labels on the page:</p>` +
        rep.buttonTexts.map(([t, n]) =>
          `<div class="r-row"><span>${n}&times;</span><span>${esc(t)}</span>
           <span></span></div>`).join('') : ''}
      ${rep.headings?.length ? `<p class="hint">Sections: ${
        esc(rep.headings.join(' · '))}</p>` : ''}`;
    await refreshAll();
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; b.textContent = 'Why did my check find nothing?'; }
});

$('#btnAdopt').addEventListener('click', async () => {
  const b = $('#btnAdopt');
  b.disabled = true; b.textContent = 'Scanning…';
  try {
    const r = await api('/actions/adopt', { method: 'POST' });
    toast(r.message, !r.ok);
    $('#adoptOut').innerHTML = r.ok && r.orphan_count
      ? `<p class="hint">Files with no matching docket entry (left alone):</p>` +
        r.orphans.map(o => `<div class="r-row r-unmatched"><span>orphan</span>
          <span>${esc(o)}</span><span>—</span></div>`).join('')
      : '';
    await refreshAll();
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; b.textContent = 'Adopt files already in this folder'; }
});

$('#btnCheck').addEventListener('click', async () => {
  const b = $('#btnCheck');
  b.disabled = true; b.textContent = 'Checking…';
  try {
    const r = await api('/actions/check-now', { method: 'POST' });
    toast(r.ok
      ? `Check finished: ${r.new_entries} new ${
          r.new_entries === 1 ? 'entry' : 'entries'}, ${r.new_documents} ` +
        `downloaded${r.adopted ? `, ${r.adopted} adopted from disk` : ''}.` +
        (r.warnings?.length ? ` ${r.warnings.length} warning(s) — see Activity.` : '')
      : r.message, !r.ok);
    await refreshAll();
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; b.textContent = 'Check now'; }
});

$('#btnPortal').addEventListener('click', async () => {
  const b = $('#btnPortal');
  b.disabled = true;
  try {
    const r = await api('/actions/open-portal', { method: 'POST' });
    toast(r.message, !r.ok);
    await refreshAll();
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; }
});

$('#btnCloseBrowser').addEventListener('click', async () => {
  try {
    const r = await api('/actions/close-browser', { method: 'POST' });
    toast(r.message);
    await refreshAll();
  } catch (e) { toast(e.message, true); }
});

$('#btnQuit').addEventListener('click', async () => {
  if (!confirm('Quit MDEC Docket Manager?\n\nScheduled checks stop until you ' +
               'open it again. Closing this window on its own leaves them running.')) return;
  try {
    const r = await api('/actions/quit', { method: 'POST' });
    if (!r.ok) { toast(r.message, true); return; }
    document.body.innerHTML =
      '<div style="font-family:var(--body);padding:4rem 2rem;max-width:32rem">' +
      '<h1 style="font-family:var(--display);font-size:1.2rem">Shut down.</h1>' +
      '<p>You can close this window. Open the app from its icon when you need it ' +
      'again.</p></div>';
    clearInterval(window.__mdecPoll);
  } catch (e) {
    // The process may die before the response lands — that's a successful quit.
    document.body.innerHTML =
      '<div style="font-family:sans-serif;padding:4rem 2rem">Shut down. ' +
      'You can close this window.</div>';
    clearInterval(window.__mdecPoll);
  }
});

async function repair(dryRun) {
  const folder = $('#repairFolder').value.trim();
  if (!folder) { toast('Enter the folder to rename.', true); return; }
  if (!dryRun && !confirm(
      `Rename the PDFs in:\n\n${folder}\n\nAn _ORIGINAL_NAMES_manifest.csv is ` +
      `written so this is reversible. Continue?`)) return;
  try {
    const r = await api('/actions/repair-rename', {
      method: 'POST', body: JSON.stringify({ folder, dry_run: dryRun })});
    const s = r.summary;
    $('#repairOut').innerHTML =
      `<p class="hint">${dryRun ? 'Dry run — nothing changed. ' : 'Renamed. '}` +
      `${s.rename} to rename, ${s.unmatched} unmatched, ${s.missing} docket ` +
      `slots with no file. Review unmatched and missing by hand — for court ` +
      `documents a wrong label is worse than no label.</p>` +
      r.actions.map(a => `<div class="r-row r-${a.status}">
        <span>${esc(a.status)}</span><span>${esc(a.file || '—')}</span>
        <span>${esc(a.target || '—')}</span></div>`).join('');
    toast(dryRun ? `Dry run: ${s.rename} file(s) would be renamed.`
                 : `Renamed ${s.rename} file(s).`);
  } catch (e) { toast(e.message, true); }
}
$('#btnRepairDry').addEventListener('click', () => repair(true));
$('#btnRepairGo').addEventListener('click', () => repair(false));

/* --- boot -------------------------------------------------------------- */

async function refreshAll() {
  await Promise.all([loadStatus(), loadEntries(), loadDocs()]);
  const active = $('.tab.is-active').dataset.tab;
  if (active === 'docket') renderDocket();
  if (active === 'documents') renderDocuments();
  if (active === 'notes') fillEntrySelect();
}

(async function boot() {
  await refreshAll();
  loadFeatures();        // not awaited — the dashboard is already usable

  // Poll while a run is in flight so the user sees progress without refreshing.
  window.__mdecPoll = setInterval(async () => {
    const busyBefore = state.status?.monitor?.busy;
    await loadStatus();
    if (busyBefore && !state.status?.monitor?.busy) await refreshAll();
  }, 4000);
})();
