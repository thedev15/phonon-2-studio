from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


_ENTITY_PATTERNS = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "url": re.compile(r"\bhttps?://[^\s]+", re.IGNORECASE),
    "number": re.compile(r"\b\d+(?:[.,]\d+)?\b"),
    "capitalized_phrase": re.compile(
        r"\b[A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,3}\b"
    ),
}

_COMMAND_PATTERNS = (
    (re.compile(r"\b(?:start|begin|launch|open)\b\s+(.+)", re.IGNORECASE), "start"),
    (re.compile(r"\b(?:stop|end|close|cancel)\b\s+(.+)", re.IGNORECASE), "stop"),
    (re.compile(r"\b(?:save|export)\b(?:\s+(.+))?", re.IGNORECASE), "save"),
    (re.compile(r"\b(?:search|find|look up)\b\s+(.+)", re.IGNORECASE), "search"),
    (re.compile(r"\b(?:set|change|update)\b\s+(.+)", re.IGNORECASE), "set"),
)


@dataclass(frozen=True)
class Entity:
    text: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class Relation:
    subject: str
    predicate: str
    object: str
    source: str


class SpeechOntology:
    """Small, deterministic ontology layer for local transcript semantics.

    This does not replace ASR or an LLM. It provides predictable structure for
    commands, entities, topics, and graph edges without sending transcript data
    off-device.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.transcript = ""
        self.turns: list[dict[str, Any]] = []
        self.entities: dict[tuple[str, str], Entity] = {}
        self.relations: dict[tuple[str, str, str], Relation] = {}
        self.topics: dict[str, int] = defaultdict(int)

    def ingest(self, text: str, *, final: bool = True) -> dict[str, Any]:
        text = " ".join(text.split()).strip()
        if not text:
            return self.snapshot()
        if final:
            self.transcript = f"{self.transcript} {text}".strip()
            self.turns.append({
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        self._extract_entities(text)
        intent, target = self._classify_intent(text)
        for topic in self._topics(text):
            self.topics[topic] += 1
        if intent and target:
            self._add_relation("user", intent, target, text)
        return self.snapshot()

    def _extract_entities(self, text: str) -> None:
        for kind, pattern in _ENTITY_PATTERNS.items():
            for match in pattern.finditer(text):
                value = match.group(0).rstrip(".,!?")
                key = (kind, value.casefold())
                self.entities[key] = Entity(value, kind, match.start(), match.end())

    def _classify_intent(self, text: str) -> tuple[str | None, str | None]:
        for pattern, intent in _COMMAND_PATTERNS:
            match = pattern.search(text)
            if match:
                target = (match.group(1) or "").strip(" .,!?")
                return intent, target or None
        if text.endswith("?") or re.match(r"^(who|what|where|when|why|how)\b", text, re.I):
            return "question", text.rstrip("?!")
        return "statement", text

    @staticmethod
    def _topics(text: str) -> set[str]:
        words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text.casefold())
        stopwords = {
            "about", "after", "could", "from", "have", "into", "just",
            "that", "the", "this", "with", "would", "your",
        }
        return {word for word in words if word not in stopwords}

    def _add_relation(self, subject: str, predicate: str, object_: str, source: str) -> None:
        relation = Relation(subject, predicate, object_, source)
        self.relations[(subject, predicate, object_.casefold())] = relation

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "phonon-ontology/v1",
            "transcript": self.transcript,
            "turns": list(self.turns),
            "entities": [asdict(entity) for entity in self.entities.values()],
            "relations": [asdict(relation) for relation in self.relations.values()],
            "topics": dict(sorted(self.topics.items(), key=lambda item: (-item[1], item[0]))),
        }
