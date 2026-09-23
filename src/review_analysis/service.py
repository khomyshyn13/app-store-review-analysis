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
        excluded_terms = {word.casefold() for word in data.get("app_name", "").split() if len(word) > 2}
        keywords = self.keyphrases.extract(reviews, sentiments, excluded_terms=excluded_terms)
        topics = extract_topics(reviews, self.sentiment, self.grouping)
        singleton_count = sum(topic["review_count"] == 1 for topic in topics)
        repeated_review_ids = {review_id for topic in topics if topic["review_count"] > 1
                               for review_id in topic["review_ids"]}
        clustering_quality = {
            "topic_count": len(topics),
            "singleton_topic_count": singleton_count,
            "singleton_topic_percentage": round(100 * singleton_count / len(topics), 2) if topics else 0,
            "reviews_in_repeated_topics": len(repeated_review_ids),
            "repeated_topic_coverage": round(100 * len(repeated_review_ids) / len(reviews), 2) if reviews else 0,
        }
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
            "clustering_quality": clustering_quality,
            "recommendations": {**recommendations, "selected_topic_ids": [t["topic_id"] for t in recommendation_topics],
                                "selection": f"top {self.recommendation_topic_limit} topics by priority score"},
        }

    def warmup(self):
        self.sentiment.warmup()
        self.grouping.warmup()
        self.keyphrases.warmup()

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
