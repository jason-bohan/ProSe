from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from prose.copilot import CopilotError, ModelSettings, SessionConfig, SourceNote
from prose.debate import COACH_PROMPT, DebateConfig, DebateSession
from prose.legal_specialist import ConsultingCoach, _packet, validate_review
from prose.model_choices import ModelChoices


class Stub:
    def __init__(self, name, *answers):
        self.settings = ModelSettings('http://localhost:11434/v1', name)
        self.answers = list(answers)
        self.calls = []

    def complete_json(self, prompt, context, **kwargs):
        self.calls.append((prompt, context, kwargs))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


SOURCE = asdict(SourceNote('RULE', 'Supplied rule', 'Relevant rule text.', authority=True))
CONTEXT = {'practice': {'topic': 'Hearsay', 'jurisdiction': 'US federal'},
           'conversation': [{'speaker': 'You', 'text': 'Offered for notice only.'}],
           'sources': [SOURCE], 'target_words': ['private vocabulary progress']}
DRAFT = {'suggestion': 'What is the purpose of the statement?', 'why': 'Clarify its use.',
         'legal_request': {'needed': True, 'question': 'Is this offered for truth or notice?'}}
REVIEW = {'analysis': 'The purpose matters; check the supplied rule.',
          'uncertainties': ['Confirm the purpose.'], 'source_ids': ['RULE']}
FINAL = {'suggestion': 'Is the warning offered only to show notice?',
         'why': 'Distinguish truth from notice.'}


def test_bounded_delegation_then_synthesis_preserves_source_provenance():
    primary, specialist = Stub('qwen', DRAFT, FINAL), Stub('saul', REVIEW)
    result = ConsultingCoach(primary, specialist).complete_json(COACH_PROMPT, CONTEXT)
    assert result['suggestion'] == FINAL['suggestion']
    assert len(primary.calls) == 2 and len(specialist.calls) == 1
    packet = specialist.calls[0][1]
    assert packet['question'] == DRAFT['legal_request']['question']
    assert packet['jurisdiction'] == 'US federal'
    assert 'target_words' not in packet and 'draft' not in packet
    review = result['legal_review']
    assert review['status'] == 'completed' and review['used_by_coach']
    assert review['law_verified'] is False
    assert review['sources'] == [{'id': 'RULE', 'title': 'Supplied rule'}]
    assert primary.calls[1][1]['legal_specialist_review']['analysis'] == REVIEW['analysis']
    assert 'legal_request' not in result


@pytest.mark.parametrize('dispatch,status', [
    ({'needed': False}, 'not_needed'), (None, 'unavailable'),
    ({'needed': 'true'}, 'unavailable'), ({'needed': True, 'question': ''}, 'unavailable'),
])
def test_invalid_or_unneeded_dispatch_never_calls_specialist(dispatch, status):
    primary = Stub('qwen', {**DRAFT, 'legal_request': dispatch})
    specialist = Stub('saul')
    result = ConsultingCoach(primary, specialist).complete_json(COACH_PROMPT, CONTEXT)
    assert result['suggestion'] == DRAFT['suggestion']
    assert result['legal_review']['status'] == status
    assert not specialist.calls and len(primary.calls) == 1


@pytest.mark.parametrize('review', [
    CopilotError('private server information'), {**REVIEW, 'source_ids': ['FAKE']},
    {**REVIEW, 'uncertainties': 'wrong type'}, {**REVIEW, 'analysis': 'x' * 1801},
])
def test_failed_review_preserves_draft_and_reports_no_completed_review(review):
    primary, specialist = Stub('qwen', DRAFT), Stub('saul', review)
    result = ConsultingCoach(primary, specialist).complete_json(COACH_PROMPT, CONTEXT)
    assert result['suggestion'] == DRAFT['suggestion']
    assert result['legal_review']['status'] == 'unavailable'
    assert result['legal_review']['used_by_coach'] is False
    assert 'private server' not in json.dumps(result)
    assert len(primary.calls) == 1


@pytest.mark.parametrize('final', [
    CopilotError('unavailable'), {'suggestion': '', 'why': 'Missing suggestion'},
    {**FINAL, 'feedback': 'x' * 701},
])
def test_invalid_synthesis_retains_draft_and_completed_specialist_notes(final):
    result = ConsultingCoach(Stub('qwen', DRAFT, final), Stub('saul', REVIEW)).complete_json(
        COACH_PROMPT, CONTEXT)
    assert result['suggestion'] == DRAFT['suggestion']
    assert result['legal_review']['status'] == 'reviewed'
    assert result['legal_review']['used_by_coach'] is False


def test_budget_exhaustion_skips_specialist(monkeypatch):
    ticks = iter([0, 0, 89, 89])
    monkeypatch.setattr('prose.legal_specialist.time.monotonic', lambda: next(ticks))
    specialist = Stub('saul')
    result = ConsultingCoach(Stub('qwen', DRAFT), specialist).complete_json(COACH_PROMPT, CONTEXT)
    assert not specialist.calls and result['legal_review']['status'] == 'unavailable'


def test_self_consultation_rejected():
    with pytest.raises(ValueError, match='different'):
        ConsultingCoach(Stub('saul'), Stub('saul'))


def test_specialist_packet_has_bounded_excerpts_and_no_vocabulary():
    packet = _packet({**CONTEXT, 'sources': [{**SOURCE, 'text': 'x' * 6000}] * 10,
                      'session': {'notes': 'n' * 12000}}, 'Question')
    assert sum(len(s['text']) for s in packet['sources']) <= 8000
    assert len(packet['notes']) <= 600
    assert 'private vocabulary' not in json.dumps(packet)
    with pytest.raises(CopilotError):
        validate_review({**REVIEW, 'source_ids': ['OTHER']}, [SOURCE])


def test_debate_integration_keeps_specialist_out_of_opponent_role():
    primary = Stub('qwen', DRAFT, FINAL, {'reply': 'How do you prove receipt?'}, DRAFT, FINAL)
    specialist = Stub('saul', REVIEW, REVIEW)
    session = DebateSession(DebateConfig('Notice', 'Show notice', legal_review=True), primary,
                            specialist=specialist, sources=(SourceNote(**SOURCE),))
    session.start()
    result = session.reply('The recipient acknowledged it.', 0)
    assert result['turn'] == 1 and result['coach']['legal_review']['status'] == 'completed'
    assert len(specialist.calls) == 2
    assert 'legal_specialist_review' not in primary.calls[2][1]


def test_registry_supports_mlx_and_separate_saul(tmp_path):
    (tmp_path / 'ai-models.json').write_text(json.dumps({
        'version': 1, 'default': 'mlx', 'legal_specialist': 'saul', 'profiles': [
            {'id': 'mlx', 'label': 'Qwen MLX', 'provider': 'mlx',
             'base_url': 'http://100.90.227.86:8083/v1', 'model': '/exact/model/path'},
            {'id': 'saul', 'label': 'Saul 7B', 'provider': 'ollama',
             'base_url': 'http://100.90.227.86:11435', 'model': 'saul'}]}))
    registry = ModelChoices(tmp_path)
    assert registry.resolve()[1].transport == 'mlx'
    assert registry.resolve()[1].model == '/exact/model/path'
    assert registry.specialist().base_url.endswith(':11435/v1')
    assert registry.status()['legal_specialist']['configured']


@pytest.mark.parametrize('config,data', [
    (SessionConfig, {}), (DebateConfig, {'topic': 'Law', 'position': 'Question it'})])
def test_review_setting_requires_boolean(config, data):
    with pytest.raises(ValueError, match='legal_review'):
        config.from_dict({**data, 'legal_review': 'false'})
