from typing import Protocol


class SentimentAnalyzer(Protocol):
    def classify(self, texts: list[str]) -> list[dict]:
        """Return ordered label/scores/chunk_count records; empty text has label=None."""
        ...

    def describe(self) -> dict: ...


class ComplaintGrouper(Protocol):
    def group(self, texts: list[str]) -> list[list[int]]:
        """Partition input indices; each group's first index is representative."""
        ...

    def describe(self) -> dict: ...


class KeyphraseExtractor(Protocol):
    def extract(self, reviews: list[dict], sentiments: list[dict]) -> dict: ...


class RecommendationGenerator(Protocol):
    def generate(self, topics: list[dict]) -> list[dict]:
        """Return topic_id, title, observation, action, verification and evidence_ids."""
        ...


class RecommendationError(RuntimeError):
    """Provider-neutral failure; adapters translate provider exceptions into this."""
