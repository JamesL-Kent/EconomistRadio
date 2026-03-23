from __future__ import annotations

import hashlib
import re
from datetime import datetime
from random import Random

from radio_agent.config import RadioSettings
from radio_agent.models import ContentItem, HostLinkScript


class HostScriptWriter:
    """Builds very short station links from the configured presenter persona."""

    _MULTISPACE = re.compile(r"\s+")

    def __init__(self, settings: RadioSettings) -> None:
        self._settings = settings

    def build_script(
        self,
        next_item: ContentItem,
        now: datetime,
        previous_item: ContentItem | None = None,
    ) -> HostLinkScript:
        host = self._settings.host
        seed = f"{previous_item.content_id if previous_item else 'lead'}:{next_item.content_id}:{now:%Y-%m-%d}"
        rng = Random(int(hashlib.sha1(seed.encode("utf-8")).hexdigest(), 16))

        opener_pool = host.bridge_templates if previous_item else host.opener_templates
        opener_template = rng.choice(opener_pool)
        teaser_template = rng.choice(host.teaser_templates)
        summary = self._teaser_summary(next_item)

        opener = opener_template.format(
            host_name=host.name,
            station_name=self._settings.station.name,
            section=next_item.section.lower(),
            previous_title=previous_item.title if previous_item else "",
        )
        teaser = teaser_template.format(
            host_name=host.name,
            station_name=self._settings.station.name,
            title=next_item.title,
            summary=summary,
            section=next_item.section.lower(),
        )

        text = self._clean(f"{opener} {teaser}")
        text = self._remove_banned_phrases(text)
        text = self._trim_to_word_limit(text, host.max_link_words)
        text = self._trim_to_sentence_limit(text, host.max_link_sentences)
        word_count = len(text.split())
        return HostLinkScript(text=text, teaser_title=next_item.title, word_count=word_count)

    def _teaser_summary(self, item: ContentItem) -> str:
        if item.announcer_intro:
            return self._sentence_fragment(item.announcer_intro)
        if item.summary:
            return self._sentence_fragment(item.summary)
        if item.section:
            return f"a sharp {item.section.lower()} report"
        return "a concise feature"

    def _sentence_fragment(self, value: str) -> str:
        fragment = value.strip()
        fragment = fragment.rstrip(".!?")
        if fragment and fragment[0].isupper():
            fragment = fragment[0].lower() + fragment[1:]
        return fragment

    def _remove_banned_phrases(self, text: str) -> str:
        cleaned = text
        for phrase in self._settings.host.banned_phrases:
            cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)
        return self._clean(cleaned)

    def _trim_to_word_limit(self, text: str, max_words: int) -> str:
        words = text.split()
        if len(words) <= max_words:
            return text
        trimmed = " ".join(words[:max_words]).rstrip(",;:")
        if trimmed[-1] not in ".!?":
            trimmed += "."
        return trimmed

    def _trim_to_sentence_limit(self, text: str, max_sentences: int) -> str:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        parts = [part for part in parts if part]
        if len(parts) <= max_sentences:
            return text
        return " ".join(parts[:max_sentences]).strip()

    def _clean(self, text: str) -> str:
        cleaned = self._MULTISPACE.sub(" ", text).strip()
        if not cleaned:
            return f"{self._settings.station.name} continues."
        if cleaned[-1] not in ".!?":
            cleaned += "."
        return cleaned
