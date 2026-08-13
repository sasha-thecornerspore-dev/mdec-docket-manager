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
PARSE_JS = r"""
() => {
  const isDocBtn = (b) => {
    const t = (b.textContent || '').trim();
    return t === 'Document' || t === 'Documents';
  };
  const btns = Array.from(document.querySelectorAll('button')).filter(isDocBtn);
  btns.forEach((b, i) => b.setAttribute('data-mdec-idx', String(i)));
  const btnIdx = new Map(btns.map((b, i) => [b, i]));

  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4'))
    .map(h => ({ h, text: (h.textContent || '').trim() }))
    .filter(x => x.text);
  const sectionFor = (el) => {
    let best = '';
    for (const { h, text } of headings) {
      if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) best = text;
    }
    return best;
  };

  // Row containers: prefer <article> (MDEC uses them heavily), fall back to <tr>.
  let rows = Array.from(document.querySelectorAll('article'));
  if (rows.length < 5) rows = Array.from(document.querySelectorAll('tr'));

  const dateRe = /\b\d{1,2}\/\d{1,2}\/\d{4}\b/;
  const entries = [];
  const claimed = new Set();

  for (const r of rows) {
    if (r.querySelector('article')) continue;            // container, not a leaf row
    const text = (r.innerText || '').replace(/\s+\n/g, '\n').trim();
    if (!text) continue;
    const rowBtns = Array.from(r.querySelectorAll('button')).filter(b => btnIdx.has(b));
    const dateMatch = text.match(dateRe);
    if (!dateMatch && rowBtns.length === 0) continue;    // not a docket row

    rowBtns.forEach(b => claimed.add(btnIdx.get(b)));
    const lines = text.split('\n').map(s => s.trim())
      .filter(s => s && s !== 'Document' && s !== 'Documents');
    // Heuristic labeled-field extraction with graceful degradation to raw text.
    const grab = (label) => {
      const i = lines.findIndex(l => l.toLowerCase().startsWith(label));
      if (i === -1) return '';
      const inline = lines[i].slice(label.length).replace(/^:\s*/, '').trim();
      return inline || (lines[i + 1] || '');
    };
    let file_date = grab('file date') || grab('created date') || (dateMatch ? dateMatch[0] : '');
    let name = grab('docket entry') || grab('document name') || '';
    let comment = grab('comment') || '';
    if (!name) {
      const cand = lines.filter(l => !dateRe.test(l) && !/^(file date|created date|comment)/i.test(l));
      name = cand[0] || '';
      if (!comment) comment = cand.slice(1).join(' | ');
    }
    entries.push({
      section: sectionFor(r),
      file_date, name, comment,
      raw_text: text.slice(0, 2000),
      button_index: rowBtns.length ? btnIdx.get(rowBtns[0]) : null,
    });
  }

  // Safety net: any Document button not inside a recognized row still becomes an entry.
  btns.forEach((b, i) => {
    if (claimed.has(i)) return;
    const holder = b.closest('article, tr, li, div') || b;
    const text = ((holder.innerText || '').trim()).slice(0, 2000);
    const dm = text.match(dateRe);
    entries.push({
      section: sectionFor(b), file_date: dm ? dm[0] : '',
      name: text.split('\n')[0] || 'Unlabeled document entry',
      comment: '', raw_text: text, button_index: i,
    });
  });

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
