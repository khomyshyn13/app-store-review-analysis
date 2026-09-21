from collections import Counter
from processing.preprocessing import preprocess_reviews
from .ports import SentimentAnalyzer, ComplaintGrouper, KeyphraseExtractor, RecommendationGenerator, RecommendationError
from .topics import extract_topics


class ReviewAnalysisService:
    def __init__(self, sentiment: SentimentAnalyzer, grouping: ComplaintGrouper,
                 keyphrases: KeyphraseExtractor,
                 recommendations: RecommendationGenerator | None = None,
                 *, recommendation_topic_limit=10):
        self.sentiment = sentiment
        self.grouping = grouping
        self.keyphrases = keyphrases
        self.recommendations = recommendations
        self.recommendation_topic_limit = recommendation_topic_limit

    def analyze(self, data):
        reviews = preprocess_reviews(data)["reviews"]
        predictions = self.sentiment.classify([r["nlp_text"] for r in reviews])
        if len(predictions) != len(reviews):
            raise ValueError("Sentiment adapter returned the wrong number of results")
        sentiments = [{"review_id": r["id"], **p} for r, p in zip(reviews, predictions)]
        counts = Counter(item["label"] for item in sentiments)
        keywords = self.keyphrases.extract(reviews, sentiments)
        topics = extract_topics(reviews, self.sentiment, self.grouping)
        recommendations = {"status": "provider_not_configured", "items": []}
        recommendation_topics = topics[:self.recommendation_topic_limit]
        if not topics:
            recommendations = {"status": "completed", "items": []}
        elif self.recommendations is not None:
            try:
                items = self.recommendations.generate(recommendation_topics)
                self._validate_recommendations(items, recommendation_topics)
                recommendations = {"status": "completed", "items": items}
            except RecommendationError as exc:
                recommendations = {"status": "failed", "items": [],
                                   "message": str(exc)}
        return {
            "status": "completed" if recommendations["status"] == "completed" else "partial",
            "sentiment": {**self.sentiment.describe(), "reviews": sentiments,
                          "counts": {label: counts[label] for label in ("positive", "negative", "neutral")},
                          "skipped_empty": counts[None]},
            "keywords": keywords,
            "topics": topics,
            "topic_method": self.grouping.describe(),
            "recommendations": {**recommendations, "selected_topic_ids": [t["topic_id"] for t in recommendation_topics],
                                "selection": f"top {self.recommendation_topic_limit} topics by unique review count"},
        }

    @staticmethod
    def _validate_recommendations(items, topics):
        evidence = {t["topic_id"]: {e["evidence_id"] for e in t["evidence"]} for t in topics}
        if not isinstance(items, list):
            raise RecommendationError("Expected recommendation list")
        if any(not isinstance(item, dict) or not isinstance(item.get("topic_id"), str) for item in items):
            raise RecommendationError("Invalid recommendation item")
        if len(items) != len(evidence) or {item["topic_id"] for item in items} != set(evidence):
            raise RecommendationError("Expected exactly one recommendation per selected topic")
        for item in items:
            if not isinstance(item, dict) or item.get("topic_id") not in evidence:
                raise RecommendationError("Unknown topic")
            if any(not isinstance(item.get(key), str) or not item[key].strip()
                   for key in ("title", "observation", "action", "verification")):
                raise RecommendationError("Missing recommendation text")
            ids = item.get("evidence_ids")
            if not isinstance(ids, list) or not ids or any(
                not isinstance(eid, str) or eid not in evidence[item["topic_id"]] for eid in ids
            ):
                raise RecommendationError("Invalid evidence references")
