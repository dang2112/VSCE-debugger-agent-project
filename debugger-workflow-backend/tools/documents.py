"""Document-only discovery, snapshotting, and bounded partner-engine execution."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from functools import lru_cache
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator
from tools.filesystem import DOCUMENT_SUFFIXES, resolve_path, scan_workspace, workspace_root

PARTNER_ROOT = Path(__file__).resolve().parent / 'Document-retrieval'
MAX_DOCUMENT_BYTES = 256000
MAX_CORPUS_BYTES = 2000000
MAX_DOCUMENTS = 100
MAX_CHUNKS = 1000


class DocumentSearchArguments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=2000)
    paths: list[str] = Field(default_factory=list, max_length=30)
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator('query')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('query must contain non-whitespace characters')
        return value.strip()


class ReadDocumentArguments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1)
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=100, ge=1, le=200)
    char_offset: int = Field(default=0, ge=0, le=256000,
                             description="Offset within the selected line range, for paging long lines")


class AdaptiveDocumentArguments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    search_id: str = Field(min_length=1, max_length=64)
    max_k: int = Field(default=5, ge=1, le=20)
    drop_threshold: float = Field(default=0.30, ge=0, le=1, allow_inf_nan=False)


@lru_cache(maxsize=4)
def load_component(name: str):
    if name not in {'exact_search', 'bm25_search', 'semantic_bert', 'adaptive_k'}:
        raise ValueError('Unknown document retrieval component')
    path = PARTNER_ROOT / (name + '.py')
    if not path.is_file():
        raise ValueError('Document-retrieval checkout missing: ' + str(path))
    spec = importlib.util.spec_from_file_location('_debugger_documents_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_snapshot(root: Path, relative: str) -> dict:
    path = resolve_path(root, relative)
    if path.suffix.lower() not in DOCUMENT_SUFFIXES:
        raise ValueError('Document tools accept Markdown documents (.md, .markdown), not source code')
    if not path.is_file():
        raise ValueError('Document not found: ' + relative)
    with path.open('rb') as stream:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError('Document exceeds the 256000-byte limit: ' + relative)
    text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    if '\x00' in text:
        raise ValueError('Binary document rejected: ' + relative)
    return {'path': path.relative_to(root).as_posix(), 'text': text,
            'sha256': hashlib.sha256(raw).hexdigest(), 'source_basis': 'disk document snapshot', 'bytes': len(raw)}


def document_corpus(workspace_path: str | None, paths: list[str]) -> dict:
    root = workspace_root(workspace_path)
    inventory = scan_workspace(root)
    visible = [e['path'] for e in inventory['entries'] if e['is_document']]
    if paths:
        selected = []
        for relative in paths:
            path = resolve_path(root, relative)
            canonical = path.relative_to(root).as_posix()
            if path.suffix.lower() not in DOCUMENT_SUFFIXES:
                raise ValueError('Document searches cannot target source code: ' + relative)
            if canonical not in visible:
                raise ValueError('Document is unavailable, excluded, or beyond the scan limit: ' + relative)
            if canonical not in selected:
                selected.append(canonical)
    else:
        selected = visible
    documents, skipped, total = [], [], 0
    for relative in selected[:MAX_DOCUMENTS]:
        try:
            document = read_snapshot(root, relative)
            if total + document['bytes'] > MAX_CORPUS_BYTES:
                skipped.append({'path': relative, 'reason': 'corpus byte budget'})
                continue
            total += document['bytes']
            documents.append(document)
        except (ValueError, OSError, UnicodeError) as exc:
            if paths:
                raise ValueError(f'Cannot read requested document {relative}: {exc}') from exc
            skipped.append({'path': relative, 'reason': str(exc)[:300]})
    return {'documents': documents, 'scope': paths or ['all visible Markdown documents'],
            'available_documents': len(visible), 'indexed_documents': len(documents),
            'corpus_truncated': inventory['scan_truncated'] or len(selected) > MAX_DOCUMENTS or bool(skipped),
            'skipped': skipped, 'scan_errors': inventory['errors']}


def read_document(workspace_path: str | None, arguments: ReadDocumentArguments) -> dict:
    corpus = document_corpus(workspace_path, [arguments.path])
    document = corpus['documents'][0]
    lines = document['text'].splitlines()
    excerpt = '\n'.join(lines[arguments.start_line - 1: arguments.start_line - 1 + arguments.max_lines])
    return {'path': document['path'], 'sha256': document['sha256'], 'source_basis': document['source_basis'],
            'start_line': arguments.start_line, 'end_line': min(len(lines), arguments.start_line - 1 + arguments.max_lines),
            'total_lines': len(lines), 'char_offset': arguments.char_offset,
            'text': excerpt[arguments.char_offset:arguments.char_offset + 12000],
            'truncated': len(excerpt) > arguments.char_offset + 12000,
            'next_char_offset': arguments.char_offset + 12000 if len(excerpt) > arguments.char_offset + 12000 else None,
            'has_more': len(excerpt) > arguments.char_offset + 12000 or arguments.start_line - 1 + arguments.max_lines < len(lines)}


def search_documents(workspace_path: str | None, arguments: DocumentSearchArguments, method: str,
                     is_cancelled: Callable[[], bool] | None = None) -> dict:
    corpus = document_corpus(workspace_path, arguments.paths)
    summary = {k: v for k, v in corpus.items() if k != 'documents'}
    if not corpus['documents']:
        return {**summary, 'method': method, 'query': arguments.query, 'results': []}
    # Semantic imports/model construction are isolated from API startup and timed.
    from tools.processes import PythonProcessRunner
    with tempfile.TemporaryDirectory(prefix='debugger-documents-') as temporary:
        directory = Path(temporary)
        request = {'method': method, 'query': arguments.query, 'top_k': arguments.top_k,
                   'documents': corpus['documents']}
        (directory / 'request.json').write_text(json.dumps(request), encoding='utf-8')
        env = os.environ.copy()
        if env.get('DOCUMENT_SEMANTIC_ALLOW_DOWNLOAD') != '1':
            env['HF_HUB_OFFLINE'] = '1'
            env['TRANSFORMERS_OFFLINE'] = '1'
        backend = Path(__file__).resolve().parents[1]
        env['PYTHONPATH'] = os.pathsep.join([str(backend), env.get('PYTHONPATH', '')])
        engine = PythonProcessRunner(sys.executable)
        code = engine._execute(['-m', 'tools.document_worker', str(directory / 'request.json'),
                                str(directory / 'response.json')], backend, env, directory / 'worker.log', 90,
                               is_cancelled)
        output = directory / 'response.json'
        if not output.is_file():
            raise RuntimeError(f'Document {method} worker failed (exit {code})')
        response = json.loads(output.read_text(encoding='utf-8'))
        if 'error' in response:
            raise RuntimeError(response['error'])
        return {**summary, 'method': method, 'query': arguments.query, **response}
