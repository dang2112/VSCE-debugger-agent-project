import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools.filesystem import project_structure, ProjectStructureArguments
from tools.documents import (DocumentSearchArguments, ReadDocumentArguments, AdaptiveDocumentArguments,
                             document_corpus, read_document, load_component)
from tools.lexical import exact_search, lexical_search
from tools.semantic import semantic_search
from tools.rag import select_document_results
from tools.document_worker import rank_documents


class DocumentRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'docs').mkdir()
        (self.root / 'src').mkdir()
        (self.root / 'README.md').write_text('# Overview\nPayments service.\n\n## Setup\nInstall the package.\n', encoding='utf-8')
        (self.root / 'docs' / 'payments.md').write_text(
            '# Payment rules\nprocess_payment rejects insufficient balance.\n\n## Retry\nRetry a temporary failure.\n\n## Refund\nRefunds are idempotent.\n', encoding='utf-8')
        (self.root / 'docs' / 'operations.md').write_text('# Logging\nLog requests.\n\n## Health\nCheck health.\n', encoding='utf-8')
        (self.root / 'src' / 'payment.py').write_text('SOURCE_ONLY_SECRET = "process_payment"')
        (self.root / '.env').write_text('SECRET=must-not-appear')
        (self.root / '.gitignore').write_text('ignored/\ndocs/private.md\n')
        (self.root / 'ignored').mkdir()
        (self.root / 'ignored' / 'secret.md').write_text('process_payment private ignored')
        (self.root / 'docs' / 'private.md').write_text('process_payment private')
        (self.root / 'docs' / '.gitignore').write_text('nested-private.md\n')
        (self.root / 'docs' / 'nested-private.md').write_text('process_payment nested private')

    def test_structure_and_nested_ignore_rules(self):
        result = project_structure(str(self.root), ProjectStructureArguments(max_depth=3))
        paths = {e['path'] for e in result['entries']}
        self.assertIn('src/payment.py', paths)
        self.assertIn('docs/payments.md', paths)
        self.assertNotIn('docs/private.md', paths)
        self.assertNotIn('docs/nested-private.md', paths)
        self.assertNotIn('.env', paths)
        self.assertFalse(result['source_contents_loaded'])
        docs = project_structure(str(self.root), ProjectStructureArguments(documents_only=True, limit=1))
        self.assertEqual(len(docs['entries']), 1)
        self.assertTrue(docs['has_more'])
        self.assertNotIn('SOURCE_ONLY_SECRET', str(result))

    def test_real_exact_bm25_and_line_provenance(self):
        args = DocumentSearchArguments(query='process_payment')
        exact = exact_search(str(self.root), args)
        lexical = lexical_search(str(self.root), args)
        for result in (exact, lexical):
            self.assertEqual(result['indexed_documents'], 3)
            self.assertEqual(result['results'][0]['path'], 'docs/payments.md')
            self.assertEqual(result['results'][0]['start_line'], 1)
            self.assertEqual(result['results'][0]['end_line'], 2)
            self.assertEqual(result['results'][0]['sha256'], hashlib.sha256((self.root/'docs/payments.md').read_bytes()).hexdigest())
            self.assertNotIn('SOURCE_ONLY_SECRET', str(result))
        self.assertEqual(exact['results'][0]['score'], 1.)

    def test_doc_boundary_empty_and_explicit_scope(self):
        for path in ('src/payment.py', '../outside.md', '.env', 'docs/private.md', 'docs/nested-private.md'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                read_document(str(self.root), ReadDocumentArguments(path=path))
        result = exact_search(str(self.root), DocumentSearchArguments(query='not-mentioned'))
        self.assertEqual(result['results'], [])
        result = read_document(str(self.root), ReadDocumentArguments(path='docs/payments.md', start_line=2, max_lines=1))
        self.assertEqual(result['text'], 'process_payment rejects insufficient balance.')
        self.assertTrue(result['has_more'])
        with self.assertRaises(ValueError):
            DocumentSearchArguments(query='  ')
        (self.root / 'docs' / 'empty.md').write_text('')
        self.assertEqual(lexical_search(str(self.root), DocumentSearchArguments(query='hello', paths=['docs/empty.md']))['results'], [])

    def test_adaptive_uses_real_engine_and_does_not_modify_original(self):
        searches = {'saved': {'method': 'semantic', 'results': [{'score': .91}, {'score': .88}, {'score': .4}]}}
        result = select_document_results(searches, AdaptiveDocumentArguments(search_id='saved'))
        self.assertEqual(result['selected_count'], 2)
        result['results'][0]['score'] = 0
        self.assertEqual(searches['saved']['results'][0]['score'], .91)
        with self.assertRaises(ValueError):
            select_document_results(searches, AdaptiveDocumentArguments(search_id='unknown'))

    def test_semantic_adapter_with_fake_embeddings_and_lazy_partner_import(self):
        class Scores:
            def __getitem__(self, index): return self
            def cpu(self): return self
            def tolist(self): return [.9] * self.count
        class Model:
            def __init__(self, name): self.count = 0
            def encode_document(self, texts, **kwargs): self.count = len(texts); return texts
            def encode_query(self, texts, **kwargs): return texts
            def similarity(self, query, documents):
                scores = Scores(); scores.count = self.count; return scores
        corpus = document_corpus(str(self.root), ['docs/payments.md'])
        load_component.cache_clear()
        try:
            with patch.dict('sys.modules', {'sentence_transformers': SimpleNamespace(SentenceTransformer=Model)}):
                result = rank_documents({'method': 'semantic', 'query': 'What if funds are low?',
                                         'top_k': 2, 'documents': corpus['documents']})
            self.assertEqual(result['results'][0]['method'], 'semantic')
            self.assertEqual(result['results'][0]['score'], .9)
        finally:
            load_component.cache_clear()

    def test_symlink_escape_rejected_when_supported(self):
        target = self.root.parent / (self.root.name + '-outside.md')
        target.write_text('outside')
        self.addCleanup(target.unlink, missing_ok=True)
        try:
            (self.root / 'escape.md').symlink_to(target)
        except OSError:
            self.skipTest('OS does not permit creating symlinks')
        with self.assertRaises(ValueError):
            read_document(str(self.root), ReadDocumentArguments(path='escape.md'))

    def test_long_sections_and_missing_optional_semantic_model(self):
        (self.root / 'docs' / 'long.md').write_text('# Long\n' + 'a' * 5990 + 'process_payment' + ' end')
        result = exact_search(str(self.root), DocumentSearchArguments(query='process_payment', paths=['docs/long.md']))
        self.assertTrue(result['results'])
        self.assertTrue(all('process_payment' in r['text'] for r in result['results']))
        import importlib.util
        if importlib.util.find_spec('sentence_transformers') is None:
            with self.assertRaisesRegex(RuntimeError, 'requirements-semantic'):
                semantic_search(str(self.root), DocumentSearchArguments(query='low funds'))
