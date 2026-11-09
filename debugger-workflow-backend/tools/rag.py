"""Adaptive selection over a persisted document search, not model-invented scores."""
from tools.documents import AdaptiveDocumentArguments, load_component
from copy import deepcopy


def select_document_results(searches: dict, arguments: AdaptiveDocumentArguments) -> dict:
    if arguments.search_id not in searches:
        raise ValueError('Unknown document search ID for this session')
    search = searches[arguments.search_id]
    selected = load_component('adaptive_k').adaptive_k(
        deepcopy(search['results']), max_k=arguments.max_k, drop_threshold=arguments.drop_threshold)
    return {'search_id': arguments.search_id, 'method': search['method'], 'results': selected,
            'selected_count': len(selected), 'candidate_count': len(search['results']),
            'note': 'Relative score-drop heuristic; scores are not correctness probabilities.'}
