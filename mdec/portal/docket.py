"""Parse the MDEC case-detail page into docket entries, and fingerprint them.

Parsing runs *inside* the page (page.evaluate) because the accessibility tree is
too heavy for this page (~1,944 articles / ~2,885 rows in the reference case).
Every Document/Documents button gets tagged with a stable `data-mdec-idx`
attribute so the downloader can target it precisely after parsing.

Fingerprints make diffing safe even though the same entry title can repeat
hundreds of times: sha1(section|file_date|name|comment) + "#" + occurrence index.
"""

from __future__ import annotations

import hashlib

# Returns [{section, file_date, name, comment, raw_text, button_index}]
# button_index is null for entries with no downloadable document.
# Fields are labelled in the page text, but the labels wrap across lines
# ("Docket Entry" / "Name:" / "Order"), so line-based reading picks up the label
# fragment instead of the value. Everything below works on whitespace-normalised
# text and reads each value up to the next known label.
PARSE_JS = r"""
() => {
  const isDocBtn = (b) => {
    const t = (b.textContent || '').trim();
    return t === 'Document' || t === 'Documents';
  };
  const btns = Array.from(document.querySelectorAll('button')).filter(isDocBtn);
  btns.forEach((b, i) => b.setAttribute('data-mdec-idx', String(i)));

  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
    .map(h => ({ h, text: (h.textContent || '').trim() }))
    .filter(x => x.text);
  const sectionFor = (el) => {
    let best = '';
    for (const { h, text } of headings) {
      if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) best = text;
    }
    return best;
  };

  const flat = (el) => (el && el.innerText || '').replace(/\s+/g, ' ').trim();
  const dateRe = /\b\d{1,2}\/\d{1,2}\/\d{4}\b/;

  // Every label the portal uses on a docket card. A value runs until the next
  // one starts, which is what makes extraction reliable without knowing the
  // field order.
  const LABELS = ['File Date', 'Docket Entry Name', 'Document Name', 'Comment',
                  'Motion', 'Sequence', 'Create Initials', 'Create Date',
                  'Update Initials', 'Update Date', 'Created Date', 'Filed By',
                  'Party1', 'Party2', 'Party3', 'Reference Number', 'Status'];
  const stop = LABELS.map(l => l.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
                     .join('|') + '|Party\\d+';
  const field = (text, label) => {
    const re = new RegExp(label + '\\s*:\\s*(.*?)\\s*(?=(?:' + stop + ')\\s*:|$)', 'i');
    const m = text.match(re);
    return m ? m[1].trim() : '';
  };

  // The row for a button is the nearest ancestor that carries real content.
  // The button often sits in its own wrapper whose whole text is "DOCUMENTS",
  // and treating that as the row is what produced files named "DOCUMENTS".
  const rowFor = (btn) => {
    const own = (btn.textContent || '').trim().length;
    const tr = btn.closest('tr');
    if (tr && flat(tr).length > own + 5) return tr;
    let el = btn.parentElement;
    while (el && el !== document.body) {
      if (flat(el).length > own + 15) return el;
      el = el.parentElement;
    }
    return btn.closest('article') || btn.parentElement || btn;
  };

  const parseRow = (row, text) => {
    let file_date = field(text, 'File Date') || field(text, 'Created Date') ||
                    field(text, 'Create Date');
    let name = field(text, 'Docket Entry Name') || field(text, 'Document Name');
    let comment = field(text, 'Comment');

    if (!file_date) {
      const m = text.match(dateRe);
      file_date = m ? m[0] : '';
    }
    if (!name) {
      // Table layouts (Court Scheduling) have no labels — use the columns,
      // dropping the cell that only holds the button.
      const cells = Array.from(row.querySelectorAll('td, th'))
        .map(td => (td.innerText || '').replace(/\s+/g, ' ').trim())
        .filter(t => t && !/^documents?$/i.test(t));
      if (cells.length) {
        name = cells[0];
        if (!comment) comment = cells.slice(1).filter(c => !dateRe.test(c)).join(' · ');
      }
    }
    if (!name) {
      const cleaned = text.replace(/\b[Dd]ocuments?\b/g, '').trim();
      name = cleaned.split(/\s{2,}|·/)[0].slice(0, 120) || 'Untitled entry';
    }
    // A date-only or label-only name is not a name.
    if (/^(name|file date|comment)\s*:?$/i.test(name) || dateRe.test(name.trim())) {
      const alt = text.replace(/^.*?Name\s*:\s*/i, '').trim();
      if (alt && !/^\d/.test(alt)) name = alt.split(/\s*(?:Comment|Motion|Sequence)\s*:/i)[0].trim();
    }

    // The button's own label sits inside the row text and otherwise ends up in
    // the filename ("… Postponement DOCUMENT.pdf").
    // Case-insensitive: the button renders as "DOCUMENT" in caps.
    const dropBtnLabel = (s) =>
      s.replace(/[\s ]*\bdocuments?\b[\s ]*$/i, '')
       .replace(/\s{2,}/g, ' ').trim();
    name = dropBtnLabel(name);
    comment = dropBtnLabel(comment);

    // Dates arrive as M/D/YYYY here and D/M/YYYY with a time in some sections.
    if (file_date) {
      file_date = file_date.split(',')[0].trim();
      const p = file_date.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
      if (p && Number(p[1]) > 12 && Number(p[2]) <= 12) {
        file_date = p[2] + '/' + p[1] + '/' + p[3];   // D/M/Y -> M/D/Y
      }
    }
    return { file_date, name: name.slice(0, 300), comment: comment.slice(0, 600) };
  };

  const entries = [];
  const seenRows = new Set();

  // Document-bearing entries first, driven by the buttons themselves so every
  // downloadable entry is represented exactly once.
  btns.forEach((b, i) => {
    const row = rowFor(b);
    seenRows.add(row);
    const text = flat(row);
    const f = parseRow(row, text);
    entries.push({
      section: sectionFor(row),
      file_date: f.file_date, name: f.name, comment: f.comment,
      raw_text: text.slice(0, 2000),
      button_index: i,
    });
  });

  // Then docket rows that have no document, so the record is complete.
  const cards = Array.from(document.querySelectorAll('article, tr'));
  for (const r of cards) {
    if (seenRows.has(r)) continue;
    if (r.querySelector('article, tr')) continue;      // container, not a leaf
    if (r.querySelector('button[data-mdec-idx]')) continue;
    const text = flat(r);
    if (!text || text.length < 12) continue;
    if (!dateRe.test(text) && !/File Date|Docket Entry/i.test(text)) continue;
    const f = parseRow(r, text);
    entries.push({
      section: sectionFor(r),
      file_date: f.file_date, name: f.name, comment: f.comment,
      raw_text: text.slice(0, 2000),
      button_index: null,
    });
  }

  return entries;
}
"""


# Structure-only report for when parsing finds nothing. Deliberately returns
# shapes and counts, plus short samples, so it can be shared to diagnose a
# portal change without handing over the contents of someone's case.
DIAGNOSE_JS = r"""
() => {
  const out = {};
  const text = document.body.innerText || '';
  out.url = location.href;
  out.title = document.title;
  out.chars = text.length;

  const btns = [...document.querySelectorAll('button')];
  out.buttonCount = btns.length;
  const tally = {};
  btns.forEach(b => {
    const t = (b.textContent || '').trim().slice(0, 30) || '(no text)';
    tally[t] = (tally[t] || 0) + 1;
  });
  out.buttonTexts = Object.entries(tally).sort((a, b) => b[1] - a[1]).slice(0, 20);

  out.containers = {
    article: document.querySelectorAll('article').length,
    tr: document.querySelectorAll('tr').length,
    table: document.querySelectorAll('table').length,
    roleRow: document.querySelectorAll('[role="row"]').length,
    roleGrid: document.querySelectorAll('[role="grid"], [role="treegrid"]').length,
    li: document.querySelectorAll('li').length,
    iframe: document.querySelectorAll('iframe').length,
  };
  out.ariaDownload = document.querySelectorAll('[aria-label*="ownload"]').length;
  out.headings = [...document.querySelectorAll('h1,h2,h3,h4')]
    .map(h => (h.textContent || '').trim()).filter(Boolean).slice(0, 20);

  // What the parser would find, so a mismatch is obvious.
  out.parserWouldFind = btns.filter(b => {
    const t = (b.textContent || '').trim();
    return t === 'Document' || t === 'Documents';
  }).length;

  const dateRe = /\b\d{1,2}\/\d{1,2}\/\d{4}\b/;
  const rows = [...document.querySelectorAll('article, tr, [role="row"]')];
  out.rowsWithDates = rows.filter(r => dateRe.test(r.innerText || '')).length;
  out.sampleRows = rows.filter(r => dateRe.test(r.innerText || ''))
    .slice(0, 3).map(r => (r.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 220));
  return out;
}
"""


async def diagnose(page) -> dict:
    """Diagnose the frame that holds the docket, and note the others."""
    frame = await content_frame(page)
    report = await frame.evaluate(DIAGNOSE_JS)
    report["frameCount"] = len(page.frames)
    report["usedMainFrame"] = frame is page.main_frame
    frames = []
    for f in page.frames:
        try:
            frames.append({"url": (f.url or "")[:120],
                           "score": await f.evaluate(SCORE_JS)})
        except Exception:
            frames.append({"url": (f.url or "")[:120], "score": None})
    report["frames"] = frames
    return report


def fingerprint(entries: list[dict]) -> list[dict]:
    """Return copies of `entries` in page order, each with a `fingerprint`.

    Copies rather than mutating in place: if the caller ever hands us the same
    dict object twice, in-place assignment would give every occurrence the last
    counter value and the diff would then treat unchanged entries as new. For a
    docket, a wrong fingerprint means a re-download or a mislabel, so the
    aliasing hazard is worth the copy.
    """
    counts: dict[str, int] = {}
    out: list[dict] = []
    for e in entries:
        base = hashlib.sha1(
            "|".join([
                e.get("section", ""), e.get("file_date", ""),
                e.get("name", ""), e.get("comment", ""),
            ]).encode("utf-8")
        ).hexdigest()[:16]
        n = counts.get(base, 0)
        counts[base] = n + 1
        out.append({**e, "fingerprint": f"{base}#{n}"})
    return out


def diff_new(entries: list[dict], known: set[str]) -> list[dict]:
    """Entries whose fingerprint the DB hasn't seen, in page order.

    Occurrence counting keeps this correct when identical entries repeat: if the
    docket had 3 copies of X and now has 5, exactly the two new copies (#3, #4)
    come back as new.
    """
    return [e for e in entries if e["fingerprint"] not in known]


# How much docket content a frame holds. The portal renders parts of the page in
# iframes, and a parser that only reads the top-level document finds nothing even
# when the docket is right there on screen.
SCORE_JS = r"""
() => {
  const btns = [...document.querySelectorAll('button')].filter(b => {
    const t = (b.textContent || '').trim();
    return t === 'Document' || t === 'Documents';
  }).length;
  const dateRe = /\b\d{1,2}\/\d{1,2}\/\d{4}\b/;
  const rows = [...document.querySelectorAll('article, tr, [role="row"]')]
    .filter(r => dateRe.test(r.innerText || '')).length;
  return btns * 10 + rows;
}
"""


async def content_frame(page):
    """The frame holding the docket — usually the main one, sometimes an iframe.

    Returns something with the same query_selector/evaluate surface as a page,
    so callers can treat it uniformly.
    """
    best, best_score = page.main_frame, -1
    for frame in page.frames:
        try:
            score = await frame.evaluate(SCORE_JS)
        except Exception:
            continue          # cross-origin or torn down mid-navigation
        if score > best_score:
            best, best_score = frame, score
    return best


async def parse_page(page) -> list[dict]:
    """Run the in-page parser and fingerprint the result (page order preserved)."""
    frame = await content_frame(page)
    entries = await frame.evaluate(PARSE_JS)
    return fingerprint(entries)
