from __future__ import annotations

from prose.hud import HudSimulator, ObjectionEngine, Teleprompter


def test_hearsay_detected() -> None:
    engine = ObjectionEngine()
    found = engine.evaluate("My brother told me the form should have been a one-time fee.")
    ids = {o.rule_id for o in found}
    assert "hearsay" in ids
    hearsay = next(o for o in found if o.rule_id == "hearsay")
    assert hearsay.citation == "FRE 802"
    assert "told me" in hearsay.hits


def test_speculation_and_leading() -> None:
    engine = ObjectionEngine()
    found = engine.evaluate("In your opinion, do you think the defendant did it?")
    ids = {o.rule_id for o in found}
    assert "speculation" in ids
    found2 = engine.evaluate("Isn't it true you signed the form?")
    assert {o.rule_id for o in found2} == {"leading"}


def test_best_evidence_and_foundation() -> None:
    engine = ObjectionEngine()
    found = engine.evaluate("Where is the original? This exhibit is just a copy.")
    ids = {o.rule_id for o in found}
    assert "best_evidence" in ids
    assert "foundation" in ids


def test_no_false_positive_on_neutral_text() -> None:
    engine = ObjectionEngine()
    assert engine.evaluate("The court will take a five minute recess.") == []
    assert engine.evaluate("Thank you. We are ready to proceed when you are.") == []


def test_confidence_scales_with_hits() -> None:
    engine = ObjectionEngine()
    found = engine.evaluate("She said it and he said it and according to the file.")
    hearsay = next(o for o in found if o.rule_id == "hearsay")
    assert hearsay.confidence > 0.5


def test_teleprompter_priority_ordering() -> None:
    tp = Teleprompter(window=3)
    tp.add("lower-priority note", "note")
    tp.add("urgent objection line", "objection")
    tp.add("mid statute line", "statute")
    assert tp.render() == [
        "urgent objection line",
        "mid statute line",
        "lower-priority note",
    ]


def test_teleprompter_window_evicts_lowest_priority() -> None:
    tp = Teleprompter(window=2)
    tp.add("note one", "note")
    tp.add("objection one", "objection")
    tp.add("objection two", "objection")
    rendered = tp.render()
    assert len(rendered) == 2
    assert rendered[0] == "objection one"


def test_hud_simulator_frame() -> None:
    hud = HudSimulator()
    frame = hud.feed(
        "Witness A: He said the fee was charged twice, my understanding is it was an error."
    )
    assert frame.seq == 1
    assert frame.transcript.speaker == "Witness A"
    assert any(o.rule_id == "hearsay" for o in frame.objections)
    assert frame.prompt is not None
    assert frame.prompt.startswith("OBJECTION:")