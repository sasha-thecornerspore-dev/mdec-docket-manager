/* MDEC Docket Manager — UI logic. No framework, no build step. */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = { status: null, entries: [], docs: [], settings: null, secrets: {} };
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
  if (name === 'settings')  loadSettings();
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

  $('#caseCaption').textContent = s.case.caption || 'MDEC Docket Manager';
  $('#caseNumber').textContent = s.case.case_number || 'No case configured';
  $('#caseCourt').textContent = s.case.court || '';
  const st = $('#monitorState');
  st.textContent = s.monitor.message || 'idle';
  st.title = s.monitor.message || 'idle';
  st.classList.toggle('is-busy', !!s.monitor.busy);
  $('#btnCheck').disabled = !!s.monitor.busy;

  const c = s.counts;
  const cells = [
    ['Docket entries', c.entries], ['Documents', c.documents],
    ['OCR done', c.ocr_done], ['Sent to RAG', c.rag_exported],
    ['Notes', c.notes], ['Analyses', c.analyses],
  ];
  $('#tally').innerHTML = cells.map(([k, n]) => `
    <div class="tally-cell"><span class="tally-n">${n}</span>
      <span class="tally-k">${k}</span></div>`).join('');

  $('#dashRuns').innerHTML = s.runs.length
    ? s.runs.map(runRow).join('') : '<p class="empty">No checks have run yet.</p>';

  const f = s.features;
  const rows = [
    [!!s.case.case_number, 'Case number set',
      'Add the case number in Settings.'],
    [s.browser_running, 'Portal browser open',
      'Click "Open portal window" and sign in.'],
    [f.analysis_enabled && f.analysis_backend !== 'none',
      `Claude analysis (${f.analysis_backend})`,
      f.analysis_why || 'Turn on analysis in Settings.'],
    [f.ocr_enabled && f.ocr_available, 'OCR ready',
      f.ocr_enabled ? f.ocr_why : 'OCR is off. Turn it on in Settings.'],
    [f.rag_targets.length > 0, `RAG export → ${f.rag_targets.join(', ') || 'none'}`,
      'No RAG target configured.'],
    [s.schedule.enabled, `Scheduled checks at ${s.schedule.times.join(', ')}`,
      'Scheduled checks are off.'],
  ];
  $('#dashChecks').innerHTML = rows.map(([ok, good, bad]) => `
    <li><span class="mark ${ok ? 'ok' : 'no'}">${ok ? '✓' : '!'}</span>
      <span>${esc(ok ? good : bad)}</span></li>`).join('');
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
  const f = state.status?.features;
  if (f) {
    $('#ocrState').textContent = f.ocr_available
      ? 'OCR tools found (Tesseract + Ghostscript).' : f.ocr_why;
    $('#analysisState').textContent = f.analysis_backend === 'none'
      ? f.analysis_why : `Using the ${f.analysis_backend === 'cli'
        ? 'Claude subscription via the Claude Code CLI' : 'Anthropic API'}.`;
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
    await refreshAll();
    loadSettings();
  } catch (e) { toast(e.message, true); }
});

/* --- actions ----------------------------------------------------------- */

$('#btnCheck').addEventListener('click', async () => {
  const b = $('#btnCheck');
  b.disabled = true; b.textContent = 'Checking…';
  try {
    const r = await api('/actions/check-now', { method: 'POST' });
    toast(r.ok
      ? `Check finished: ${r.new_entries} new ${
          r.new_entries === 1 ? 'entry' : 'entries'}, ${r.new_documents} new ${
          r.new_documents === 1 ? 'document' : 'documents'}.` +
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
  // Poll while a run is in flight so the user sees progress without refreshing.
  setInterval(async () => {
    const busyBefore = state.status?.monitor?.busy;
    await loadStatus();
    if (busyBefore && !state.status?.monitor?.busy) await refreshAll();
  }, 4000);
})();
