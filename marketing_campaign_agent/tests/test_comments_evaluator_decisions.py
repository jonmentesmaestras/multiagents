import json

from marketing_campaign_agent.tools.comments_evaluator_tool import evaluate_classified_comments_metrics


def row(i, decision, failure_kind=None):
    return {'comment_id': str(i), 'categoria': decision, 'decision': decision,
            'failure_kind': failure_kind, 'deseo': 'D' if decision == 'deseo' else None,
            'problema': 'P' if decision == 'problema' else None}


def test_semantic_review_does_not_make_complete_processing_incomplete():
    rows = [row(1, 'deseo'), row(2, 'problema'), row(3, 'requiere_revision', 'semantic_ambiguity')]
    result = evaluate_classified_comments_metrics(rows, source_comments=rows)
    assert result['coverage']['status'] == 'verified'
    assert result['decision'] == 'DO_NOT_ACCEPT_OFFER'
    assert result['technical_error_count'] == 0
    assert result['semantic_review_count'] == 1
    assert result['maximum_possible_relevant'] == 3


def test_ambiguous_comments_that_could_reach_threshold_require_human_review():
    rows = ([row(i, 'deseo') for i in range(49)] +
            [row(i + 49, 'problema') for i in range(49)] +
            [row(98, 'requiere_revision', 'semantic_ambiguity'), row(99, 'requiere_revision', 'semantic_ambiguity')])
    result = evaluate_classified_comments_metrics(json.dumps(rows), source_comments=rows)
    assert result['decision'] == 'HUMAN_REVIEW_REQUIRED'
    assert result['total_classified'] == 98
    assert result['maximum_possible_relevant'] == 100


def test_technical_failure_remains_incomplete():
    rows = [row(1, 'deseo'), row(2, 'requiere_revision', 'technical_error')]
    result = evaluate_classified_comments_metrics(rows, source_comments=rows)
    assert result['decision'] == 'INCOMPLETE_ANALYSIS'
    assert result['technical_error_count'] == 1


def test_confirmed_threshold_is_accepted_even_with_semantic_review():
    rows = [row(i, 'deseo') for i in range(100)] + [row(100, 'requiere_revision', 'semantic_ambiguity')]
    result = evaluate_classified_comments_metrics(rows, source_comments=rows)
    assert result['decision'] == 'ACCEPT_OFFER'
    assert result['is_offer_accepted'] is True


def test_threshold_does_not_override_incomplete_source_coverage():
    classified = [row(i, 'deseo') for i in range(100)]
    source = classified + [row(100, 'no_aplica')]
    result = evaluate_classified_comments_metrics(
        classified,
        source_comments=source,
        collection_status={'status': 'complete'},
        classification_status={'status': 'complete', 'target_reached': True},
    )
    assert result['coverage']['status'] == 'incomplete'
    assert result['decision'] == 'INCOMPLETE_ANALYSIS'
    assert result['is_offer_accepted'] is None


def test_safe_positive_early_stop_accepts_incomplete_source_coverage():
    classified = [row(i, 'deseo') for i in range(100)]
    source = classified + [row(100 + i, 'no_aplica') for i in range(25)]
    result = evaluate_classified_comments_metrics(
        classified,
        source_comments=source,
        collection_status={'status': 'complete'},
        classification_status={
            'status': 'complete_early',
            'target_reached': True,
            'stop_reason': 'target_reached',
            'technical_error_count': 0,
            'invalid_source_count': 0,
        },
    )
    assert result['coverage']['status'] == 'incomplete'
    assert result['decision'] == 'ACCEPT_OFFER'
    assert result['is_offer_accepted'] is True


def test_unsafe_early_stop_remains_incomplete():
    classified = [row(i, 'deseo') for i in range(100)]
    source = classified + [row(100, 'no_aplica')]
    result = evaluate_classified_comments_metrics(
        classified,
        source_comments=source,
        collection_status={'status': 'complete'},
        classification_status={
            'status': 'complete_early',
            'target_reached': True,
            'stop_reason': 'target_reached',
            'technical_error_count': 1,
            'invalid_source_count': 0,
        },
    )
    assert result['decision'] == 'INCOMPLETE_ANALYSIS'
    assert result['is_offer_accepted'] is None


def test_only_combined_relevant_total_determines_market_threshold():
    cases = [
        (51, 0, 'DO_NOT_ACCEPT_OFFER'),
        (50, 49, 'DO_NOT_ACCEPT_OFFER'),
        (51, 49, 'ACCEPT_OFFER'),
        (30, 70, 'ACCEPT_OFFER'),
        (0, 100, 'ACCEPT_OFFER'),
    ]
    for desires, problems, expected in cases:
        rows = ([row(i, 'deseo') for i in range(desires)]
                + [row(desires + i, 'problema') for i in range(problems)])
        result = evaluate_classified_comments_metrics(rows, source_comments=rows)
        assert result['decision'] == expected, (desires, problems)
