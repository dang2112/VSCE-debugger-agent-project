# Documentation and project overview tools

In `mode: "agent"`, the LLM can inspect the project layout and search **supporting
documents** independently of source-code retrieval and SBFL. Documentation may
explain intended behavior, business rules, or architecture; it does not establish
what the implementation actually does. No fixed exact -> lexical -> semantic
pipeline is enforced.

## Exposed tools

| Tool | Purpose |
| --- | --- |
| `project_structure` | File/directory paths, file types, and documentation locations; no contents |
| `document_exact_search` | Literal, case-insensitive identifier or phrase matching in documents |
| `document_lexical_search` | BM25 relevance across the shared document corpus |
| `document_semantic_search` | Sentence-BERT similarity over document chunks |
| `document_adaptive_k` | Score-drop selection from an existing session search ID |
| `read_document` | Line-addressed document excerpt for follow-up reading |
| `read_file` | Existing extension action for source/editor snapshots; separate from document tools |

These tools currently operate on a **backend-accessible workspace** supplied in
`context.workspace_path`. Remote-only extension workspaces need a future document
inventory/content bridge; source file reads already use the extension bridge.
Document tools do not silently request or search source files.

Examples of tool arguments:

```json
{"path": ".", "max_depth": 3, "limit": 200, "documents_only": false}
```

```json
{"query": "process_payment", "paths": ["docs/payments.md"], "top_k": 5}
```

```json
{"query": "What should happen when the available balance is too low?", "top_k": 5}
```

```json
{"search_id": "ID returned by a prior search", "max_k": 5, "drop_threshold": 0.3}
```

```json
{"path": "docs/payments.md", "start_line": 20, "max_lines": 80}
```

Search `paths` selects specific Markdown files. An empty list discovers visible
Markdown documents in the project. Supported formats are `.md` and `.markdown`,
not Python/JavaScript source, PDFs, Word documents, HTML, or notebooks. Markdown
code examples remain part of their containing documentation.

## Integration with the partner repository

The partner checkout stays at `tools/Document-retrieval` and is not modified.
Adapters load modules by explicit filename without importing its demo `main.py`
or adding generic names to the process import path.

- `tools/filesystem.py`: workspace containment, nested `.gitignore` handling,
  metadata-only discovery and project overview.
- `tools/documents.py`: document snapshots, validated arguments, byte limits,
  reading, and worker execution.
- `tools/document_worker.py`: uses the partner Markdown heading chunker,
  BM25 tokenizer/class, and Sentence-BERT model. Literal search uses the same
  case-insensitive occurrence-count semantics as its exact-search function.
- `tools/lexical.py`: exact and lexical adapters.
- `tools/semantic.py`: semantic adapter.
- `tools/rag.py`: calls the partner's `adaptive_k` on backend-recorded results.
  It performs selection, not answer generation.
- `tools/processes.py`: shared timeout/cancellation subprocess runner for
  retrieval and SBFL.

The partner MVP fits BM25 independently for one document. Those independently
fitted scores would not be comparable across files, so the adapter fits the
partner BM25 class on all selected chunks together. Semantic embeddings likewise
share one corpus. Large heading sections use overlapping 6000-character windows
with a 4000-character stride. Scores are method-specific, not confidence or
correctness probabilities; results from separate queries/methods should not be
compared directly. Nonpositive scores are omitted, including semantic scores.

## Setup

Install `requirements.txt` for exact search, project discovery, and BM25:

```powershell
python -m venv --system-site-packages .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Semantic search is optional because its model packages and weights are much
larger. Install `requirements-semantic.txt` explicitly to enable it, then provision
`sentence-transformers/all-MiniLM-L6-v2` in the local model cache. Semantic imports
and model construction occur only inside a worker when that tool is called; API
startup, SBFL, exact search, and BM25 do not load Sentence-BERT or PyTorch.

Model downloads are disabled in retrieval workers by default. An operator who
wants the first semantic call to provision weights can set
`DOCUMENT_SEMANTIC_ALLOW_DOWNLOAD=1` before starting the backend. Model construction
and retrieval still share the 90-second call timeout. Offline cache/dependency
errors become tool observations, allowing the agent to choose another method;
there is no hidden lexical fallback pretending to be semantic retrieval.

The optional packages/weights have not been installed by this change. Only
`rank-bm25` and `pathspec` were added to this repository's virtual environment.
The nested partner clone must be provisioned separately when deploying elsewhere.

## Evidence, scope, and budgets

Results carry workspace-relative paths, heading/chunk/segment IDs, line ranges,
raw snapshot SHA-256 hashes, method/score, and a disk-source label. Search result
text is an excerpt of the indexed window and explicitly marks truncation. Every
returned excerpt is recorded as typed document/lexical/semantic evidence with an
`evidence_id`; it is not appended to source-code context. Search IDs/results
persist across backend restarts and extension file-read pauses. Adaptive-K accepts
only a search ID belonging to the current session, not model-supplied scores.
It selects from the saved candidate shortlist, not the entire original corpus.

Discovery skips hidden paths (except `.github`), generated directories, dependency
folders, symlinks, and files excluded by nested `.gitignore` rules. Explicit
requests cannot bypass those exclusions. This is a read-only local adapter, not a
filesystem sandbox; it does not replace extension workspace trust/access checks.
Symlink and containment checks are made before reading. Files can change between
calls; hashes identify the snapshots actually retrieved.

Bounds per operation:

- At most 10,000 directory entries inspected, discovery depth 32; overview depth
  defaults to 3 and returns up to 200 entries with offset pagination.
- Up to 100 documents, 256,000 bytes each, 2,000,000 corpus bytes, and 1,000 chunks.
- Search top-k defaults to 5 and is capped at 20; returned search text is capped
  at 1,800 characters per hit.
- `read_document` returns up to 200 requested lines and 12,000 characters. Use its
  `next_char_offset` with the same line range to page through unusually long lines.
- A session shares an 80,000-character document evidence budget across searches,
  reads, and adaptive selections. It is separate from the source-code budget.
- Worker calls time out after 90 seconds and honor session cancellation.

Partial corpus scans, skipped documents, chunk limits, pagination, and text
truncation are reported. Search coverage is limited to that explicitly reported
corpus, not a guarantee that no relevant document exists elsewhere.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests exercise the real partner chunker, real BM25 and adaptive selection, ignore
rules, document/source boundaries, provenance, persistence, and agent dispatch.
Gemini and semantic embedding computation are mocked. A symlink test runs only
where the OS permits creating symlinks.
