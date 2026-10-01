from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .briefing import StageBriefing, brief_for_stage
from .crawler import MockFTCSource, MockPACERSource, Source, collect
from .device import HudTransport
from .docs import Draft, build_docs
from .hud import HudFrame, HudSimulator
from .matcher import BankRow, MatchResult, Purchase, Subscription, UserRecord, evaluate
from .state_machine import Case
from .tagger import SAMPLE_RAW_COMPLAINT, TagSet, tag_text

MIN_AUTO_CONFIDENCE = 0.75

SAMPLE_RECORD = UserRecord(
    party="Janet A. Doe",
    purchases=(
        Purchase(
            item="Voltmax 20,000 mAh Power Bank",
            sku="VLX-200",
            merchant="Voltmax Direct",
            purchased_on=date(2024, 3, 14),
            price=59.99,
        ),
    ),
    subscriptions=(
        Subscription(name="FitTrack Pro", monthly_fee=9.99, auto_renew=True, opted_out=False),
    ),
    bank_rows=(
        BankRow(posted_on=date(2025, 7, 2), description="STATE CARD LATE FEE", amount=30.00),
        BankRow(posted_on=date(2025, 11, 2), description="STATE CARD LATE FEE", amount=30.00),
        BankRow(posted_on=date(2026, 2, 2), description="STATE CARD LATE FEE", amount=30.00),
    ),
)

SAMPLE_TRANSCRIPT = (
    "Counsel Q: In your opinion, do you think the defendant made the subscription form deceptive?",
    "Counsel Q: Isn't it true you never noticed the charge on the account statement?",
    (
        "Witness A: My brother told me the form should have been a one-time fee, "
        "and my understanding is it would never auto-renew."
    ),
    (
        "Court: Counsel, where is the original contract? Exhibit 4 is just a copy of "
        "Exhibit 3 - move to authenticate the document."
    ),
    "Counsel Q: Let the record reflect the plaintiff never consented to recurring billing.",
)


@dataclass
class PipelineResult:
    total_violations: int
    matches: list[MatchResult] = field(default_factory=list)
    review: list[MatchResult] = field(default_factory=list)
    drafts: list[tuple[str, Draft]] = field(default_factory=list)
    case: Case | None = None
    briefing: StageBriefing | None = None
    tags: TagSet | None = None
    frames: list[HudFrame] = field(default_factory=list)

    def to_text(self) -> str:
        lines = ["Project JusticeStack / LexGlasses - end-to-end simulation", "=" * 64]
        lines.append(f"Crawled violations                        : {self.total_violations}")
        lines.append(f"Matches (auto, >= {MIN_AUTO_CONFIDENCE:.2f})      : {len(self.matches)}")
        for match in self.matches:
            lines.append("")
            lines.append(match.to_summary())
        lines.append(f"Held for human review (manual verification)    : {len(self.review)}")
        for match in self.review:
            lines.append("")
            lines.append(match.to_summary())
            lines.append("  -> no document auto-generated; verify manually before acting")
        if self.case is not None:
            case = self.case
            lines.append("")
            lines.append(f"Case {case.case_number} ({case.cause}) - now at {case.stage}")
            lines.extend(f"  {day} | {entry}" for day, entry in case.history)
        if self.briefing is not None:
            lines.append("")
            lines.append("Stage briefing (pre-prepared, for mobile prompt / human review):")
            lines.append(self.briefing.to_text())
        if self.tags is not None:
            lines.append("")
            lines.append("Entity tags (batch text extraction, no real-time inference):")
            lines.extend(f"  {line}" for line in self.tags.summary().splitlines())
        lines.append("")
        lines.append(f"Draft documents (templates only, review before use)    : {len(self.drafts)}")
        lines.extend(f"  [{vid}] {d.doc_type} -> {d.document_id}" for vid, d in self.drafts)
        lines.extend(["", "Glasses HUD - scripted objection/teleprompter feed", "-" * 64])
        for frame in self.frames:
            lines.append(f"#{frame.seq} {frame.transcript.speaker}: {frame.transcript.text}")
            if frame.objections:
                for objection in frame.objections:
                    lines.append(
                        f"   OBJECTION  {objection.label} ({objection.citation}) "
                        f"conf={objection.confidence:.2f}"
                    )
                lines.append(f"   HUD PROMPT> {frame.prompt}")
            else:
                lines.append("   HUD: -- no prompt --")
        lines.append("")
        lines.append("DISCLAIMER: simulation output. Not legal advice; not for filing.")
        return "\n".join(lines)


def run(
    record: UserRecord | None = None,
    transcript: tuple[str, ...] | None = None,
    raw_text: str | None = None,
    sources: list[Source] | None = None,
    rate_limit_seconds: float = 0.0,
    transport: HudTransport | None = None,
) -> PipelineResult:
    record = record or SAMPLE_RECORD
    transcript = transcript or SAMPLE_TRANSCRIPT
    raw_text = raw_text or SAMPLE_RAW_COMPLAINT

    violations = collect(sources or [MockPACERSource(), MockFTCSource()], rate_limit_seconds)
    found = [m for v in violations if (m := evaluate(v, record)) is not None]
    found.sort(key=lambda m: m.confidence, reverse=True)
    matches = [m for m in found if m.confidence >= MIN_AUTO_CONFIDENCE]
    review = [m for m in found if m.confidence < MIN_AUTO_CONFIDENCE]

    drafts: list[tuple[str, Draft]] = []
    case: Case | None = None
    briefing: StageBriefing | None = None
    if matches:
        case = Case(
            case_number="26-cv-00417",
            party=record.party,
            cause=matches[0].violation.program,
        )
        case.advance("FILED", "complaint filed")
        briefing = brief_for_stage(case.stage)
        for match in matches:
            for draft in build_docs(
                match,
                party=record.party,
                case_number=case.case_number,
                court="United States District Court",
                issued=date.today().isoformat(),
            ):
                drafts.append((match.violation.id, draft))

    hud = HudSimulator()
    frames: list[HudFrame] = []
    for line in transcript:
        frame = hud.feed(line)
        frames.append(frame)
        if transport is not None:
            transport.send(frame)
    if transport is not None:
        transport.close()

    tags = tag_text(raw_text)
    return PipelineResult(
        total_violations=len(violations),
        matches=matches,
        review=review,
        drafts=drafts,
        case=case,
        briefing=briefing,
        tags=tags,
        frames=frames,
    )