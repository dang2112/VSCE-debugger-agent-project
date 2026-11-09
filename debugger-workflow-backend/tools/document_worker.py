"""Isolated document ranking worker using the partner project's components."""
import json
import math
from pathlib import Path
import sys
import tempfile

from tools.documents import MAX_CHUNKS, load_component


def rank_documents(payload: dict) -> dict:
    chunks = []
    truncated = False
    chunker = load_component('exact_search').load_markdown_chunks
    with tempfile.TemporaryDirectory(prefix='doc-chunks-') as temporary:
        for index, document in enumerate(payload['documents']):
            snapshot = Path(temporary) / f'{index}.md'
            snapshot.write_text(document['text'], encoding='utf-8')
            cursor = 0
            for chunk_id, text in enumerate(chunker(str(snapshot))):
                start = document['text'].find(text, cursor)
                if start < 0:
                    raise ValueError('Cannot map document chunk to source lines')
                cursor = start + len(text)
                # Bound long heading sections without silently dropping their tail.
                for segment, offset in enumerate(range(0, max(1, len(text) - 2000), 4000)):
                    part = text[offset:offset + 6000]
                    position = start + offset
                    chunks.append({'path': document['path'], 'chunk_id': chunk_id, 'segment': segment,
                                   'start_line': document['text'].count('\n', 0, position) + 1,
                                   'end_line': document['text'].count('\n', 0, position + len(part)) + 1,
                                   'heading': text.splitlines()[0][:300] if text.startswith('#') else None,
                                   'sha256': document['sha256'], 'source_basis': document['source_basis'], 'text': part})
                    if len(chunks) >= MAX_CHUNKS:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
    method, query = payload['method'], payload['query']
    if not chunks:
        return {'results': [], 'indexed_chunks': 0, 'chunks_truncated': truncated}
    if method == 'exact':
        scores = [float(c['text'].lower().count(query.lower())) for c in chunks]
    elif method == 'bm25':
        partner = load_component('bm25_search')
        tokenized = [partner.tokenize(c['text']) for c in chunks]
        # The upstream one-document function cannot compare independently fitted
        # scores across documents. Fit its BM25 class on the shared corpus instead.
        if not any(tokenized):
            scores = [0.] * len(chunks)
        else:
            scores = partner.BM25Okapi(tokenized).get_scores(partner.tokenize(query)).tolist()
    elif method == 'semantic':
        partner = load_component('semantic_bert')
        embeddings = partner.model.encode_document([c['text'] for c in chunks], normalize_embeddings=True, convert_to_tensor=True)
        embedded_query = partner.model.encode_query([query], normalize_embeddings=True, convert_to_tensor=True)
        scores = partner.model.similarity(embedded_query, embeddings)[0].cpu().tolist()
    else:
        raise ValueError('Unknown document search method')
    if len(scores) != len(chunks) or any(not math.isfinite(float(score)) for score in scores):
        raise ValueError('Retrieval engine returned invalid scores')
    results = [{**chunk, 'score': float(score), 'method': method} for chunk, score in zip(chunks, scores)
               if float(score) > 0]
    results.sort(key=lambda c: (-c['score'], c['path'], c['chunk_id'], c['segment']))
    return {'results': results[:payload['top_k']], 'indexed_chunks': len(chunks), 'chunks_truncated': truncated,
            'score_scope': 'shared document corpus', 'score_is_probability': False}


def main():
    request, output = map(Path, sys.argv[1:3])
    try:
        result = rank_documents(json.loads(request.read_text(encoding='utf-8')))
    except Exception as exc:
        result = {'error': f'Document retrieval unavailable ({type(exc).__name__}): {str(exc)[:1500]}. '
                  'Install requirements.txt for BM25; requirements-semantic.txt and cached model weights for semantic search.'}
    output.write_text(json.dumps(result, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
