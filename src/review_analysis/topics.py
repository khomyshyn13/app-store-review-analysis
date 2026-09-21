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
        ordered = indices
        result.append({"review_ids": ids, "review_count": len(ids),
                       "percentage": round(100 * len(ids) / len(reviews), 2),
                       "representative_quote": complaints[ordered[0]]["quote"],
                       "evidence": [complaints[i] for i in ordered]})
    result.sort(key=lambda group: (-group["review_count"], group["representative_quote"]))
    return [{"topic_id": f"topic-{i+1}", **group} for i, group in enumerate(result)]
