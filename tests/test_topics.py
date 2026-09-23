from review_analysis.topics import extract_topics


class Sentiment:
    def classify(self, texts):
        return [{"label": "negative"} for _ in texts]


class Grouper:
    def group(self, texts):
        return [list(range(len(texts)))]


def test_topic_priority_uses_share_and_rating():
    reviews = [
        {"id": "a", "nlp_text": "Crashes every time.", "rating": 1},
        {"id": "b", "nlp_text": "Cannot log in.", "rating": 2},
    ]
    topic = extract_topics(reviews, Sentiment(), Grouper())[0]
    assert topic["review_count"] == 2
    assert topic["average_rating"] == 1.5
    assert topic["priority_score"] == 95.0
    assert topic["seriousness"] == "high"
