import re
from .ports import SentimentAnalyzer, ComplaintGrouper


def extract_topics(reviews, sentiment: SentimentAnalyzer, grouper: ComplaintGrouper):
    fragments = []
    for review in reviews:
        text = review["nlp_text"]
        for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", text):
            quote = match.group().strip()
            if not quote:
                continue
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            fragments.append({"review_id": review["id"], "quote": quote,
                              "start": start, "end": start + len(quote)})
    predictions = sentiment.classify([item["quote"] for item in fragments])
    if len(predictions) != len(fragments):
        raise ValueError("Sentiment adapter returned the wrong number of fragments")
    complaints = [{"evidence_id": f"e{i}", **item} for i, (item, prediction)
                  in enumerate(zip(fragments, predictions)) if prediction["label"] == "negative"]
    if not complaints:
        return []
    groups = grouper.group([item["quote"] for item in complaints])
    indices = [index for group in groups for index in group]
    if any(not group for group in groups) or sorted(indices) != list(range(len(complaints))):
        raise ValueError("Grouping adapter must partition all complaint indices exactly once")
    result = []
    for indices in groups:
        ids = sorted({complaints[i]["review_id"] for i in indices})
        selected_reviews = [review for review in reviews if review["id"] in ids]
        ratings = [review["rating"] for review in selected_reviews if isinstance(review.get("rating"), int)]
        average_rating = sum(ratings) / len(ratings) if ratings else 3.0
        share = len(ids) / max(len(reviews), 1)
        severity = (5 - average_rating) / 4
        priority_score = round(100 * (0.6 * share + 0.4 * severity), 1)
        seriousness = "high" if priority_score >= 45 else "medium" if priority_score >= 25 else "low"
        ordered = indices
        result.append({"review_ids": ids, "review_count": len(ids),
                       "percentage": round(100 * len(ids) / len(reviews), 2),
                       "average_rating": round(average_rating, 2),
                       "priority_score": priority_score,
                       "seriousness": seriousness,
                       "representative_quote": complaints[ordered[0]]["quote"],
                       "evidence": [complaints[i] for i in ordered]})
    result.sort(key=lambda group: (-group["priority_score"], -group["review_count"], group["representative_quote"]))
    return [{"topic_id": f"topic-{i+1}", **group} for i, group in enumerate(result)]
