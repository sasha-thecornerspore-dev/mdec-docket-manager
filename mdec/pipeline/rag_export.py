"""Feed extracted document text to the user's RAG app.

Three targets, any combination, all configured in Settings:

- folder:  write <catalog-name>.txt + .meta.json into an export folder the RAG
           app watches. Zero-integration option.
- webhook: HTTP POST {case_number, entry, document, text, metadata} to a URL.
- chroma:  upsert into a local ChromaDB collection (optional dependency).

Failures raise with a clear message; the monitor logs them per-document and
marks the run 'warning' rather than dying.
"""

from __future__ import annotations

import json
from pathlib import Path


def export_document(cfg: dict, case_number: str, entry: dict, doc: dict,
                    text: str) -> list[str]:
    """Run every enabled exporter. Returns the list of targets that succeeded."""
    rag = cfg["rag"]
    done: list[str] = []
    meta = {
        "case_number": case_number,
        "seq": entry.get("seq"),
        "file_date": entry.get("file_date"),
        "entry_name": entry.get("name"),
        "document_title": doc.get("title"),
        "filename": doc.get("filename"),
        "sha256": doc.get("sha256"),
    }
    if rag.get("folder_enabled") and rag.get("folder_path"):
        _to_folder(Path(rag["folder_path"]), doc, text, meta)
        done.append("folder")
    if rag.get("webhook_enabled") and rag.get("webhook_url"):
        _to_webhook(rag["webhook_url"], case_number, entry, doc, text, meta)
        done.append("webhook")
    if rag.get("chroma_enabled") and rag.get("chroma_path"):
        _to_chroma(rag, case_number, doc, text, meta)
        done.append("chroma")
    return done


def _to_folder(folder: Path, doc: dict, text: str, meta: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    stem = Path(doc.get("filename") or f"doc_{doc.get('id', 'x')}").stem
    (folder / f"{stem}.txt").write_text(text, encoding="utf-8")
    (folder / f"{stem}.meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")


def _to_webhook(url: str, case_number: str, entry: dict, doc: dict,
                text: str, meta: dict) -> None:
    import requests
    resp = requests.post(url, json={
        "case_number": case_number,
        "entry": {k: entry.get(k) for k in ("seq", "file_date", "name", "comment")},
        "document": {k: doc.get(k) for k in ("id", "title", "filename", "sha256")},
        "text": text,
        "metadata": meta,
    }, timeout=30)
    resp.raise_for_status()


def _to_chroma(rag: dict, case_number: str, doc: dict, text: str, meta: dict) -> None:
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("chromadb is not installed — pip install chromadb, "
                           "or disable the Chroma export target.") from exc
    client = chromadb.PersistentClient(path=rag["chroma_path"])
    coll = client.get_or_create_collection(rag.get("chroma_collection") or "mdec-docket")
    doc_id = f"{case_number}:{doc.get('sha256') or doc.get('filename')}"
    coll.upsert(ids=[doc_id], documents=[text[:60000]],
                metadatas=[{k: str(v) for k, v in meta.items() if v is not None}])
