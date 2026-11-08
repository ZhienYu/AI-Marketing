"""Read-only presentation model for evidence-linked business reports."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CommentSource:
    label: str
    video_id: str
    comment_id: str
    text: str
    published_at: str
    analysis_status: str

    def __post_init__(self):
        if (
            not re.fullmatch(r"S[0-9]+", self.label)
            or not re.fullmatch(r"[A-Za-z0-9_-]{11}", self.video_id)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", self.comment_id)
            or not self.text.strip()
            or self.analysis_status not in {"validated", "exploratory", "unverified", "raw"}
        ):
            raise ValueError("Invalid report source.")

    @property
    def url(self):
        return f"https://www.youtube.com/watch?v={self.video_id}&lc={self.comment_id}"


@dataclass(frozen=True)
class ReportItem:
    title: str
    detail: str
    sources: tuple[str, ...]
    badge: str = ""
    business_meaning: str = ""


@dataclass(frozen=True)
class ReportTopic:
    parent: ReportItem
    children: tuple[ReportItem, ...]


@dataclass(frozen=True)
class ReportCoverage:
    collected: int
    submitted: int
    qualitative: int
    formal: int
    collected_videos: int


@dataclass(frozen=True)
class BusinessReportView:
    topic: str
    demo: bool
    sources: tuple[CommentSource, ...]
    summary: tuple[ReportItem, ...] = ()
    topics: tuple[ReportItem, ...] = ()
    needs: tuple[ReportItem, ...] = ()
    purchase: tuple[ReportItem, ...] = ()
    competitors: tuple[ReportItem, ...] = ()
    opportunities: tuple[ReportItem, ...] = ()
    limitations: tuple[str, ...] = ()
    coverage: ReportCoverage | None = None
    research_layout: bool = False
    topic_groups: tuple[ReportTopic, ...] = ()
    scenarios: tuple[ReportItem, ...] = ()
    information_types: tuple[ReportItem, ...] = ()

    def __post_init__(self):
        source_labels = {source.label for source in self.sources}
        if (
            len(source_labels) != len(self.sources)
            or len({source.comment_id for source in self.sources}) != len(self.sources)
        ):
            raise ValueError("Report sources must be unique.")
        usable = source_labels if self.demo else {
            source.label for source in self.sources if source.analysis_status in {"validated", "exploratory"}
        }
        for topic in self.topic_groups:
            if set(topic.parent.sources) != {ref for item in topic.children for ref in item.sources}:
                raise ValueError("Topic count must equal its child source union.")
        for section in (
            self.summary, self.topics, self.needs, self.purchase,
            self.competitors, self.opportunities, self.scenarios, self.information_types,
            tuple(item for group in self.topic_groups for item in (group.parent, *group.children)),
        ):
            for item in section:
                if not item.sources or not set(item.sources) <= usable:
                    raise ValueError("Report item lacks an eligible source.")

    @property
    def video_count(self):
        return len({source.video_id for source in self.sources})

    @property
    def validated_count(self):
        return sum(source.analysis_status == "validated" for source in self.sources)

    def mentions(self, item):
        return len(set(item.sources))
