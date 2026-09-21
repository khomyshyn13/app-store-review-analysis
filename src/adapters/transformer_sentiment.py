from functools import lru_cache
from threading import Lock

LOCK = Lock()


@lru_cache(maxsize=1)
def get_model(model_name):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name).eval()
    return tokenizer, model


def classify(texts, model_name, batch_size):
    if not texts:
        return []
    import torch
    with LOCK:
        tokenizer, model = get_model(model_name)
        labels = [model.config.id2label[i].lower() for i in range(3)]
        if set(labels) != {"positive", "negative", "neutral"}:
            raise ValueError("Unexpected sentiment model labels")
        chunks, owners, weights = [], [], []
        for i, text in enumerate(texts):
            tokens = tokenizer.encode(text, add_special_tokens=False, truncation=False)
            capacity = min(tokenizer.model_max_length, 512) - tokenizer.num_special_tokens_to_add(False)
            for start in range(0, len(tokens), capacity):
                piece = tokens[start:start + capacity]
                chunks.append(tokenizer.prepare_for_model(piece, return_attention_mask=True))
                owners.append(i)
                weights.append(len(piece))
        totals = [[0.0] * 3 for _ in texts]
        denominators, counts = [0] * len(texts), [0] * len(texts)
        with torch.inference_mode():
            for start in range(0, len(chunks), batch_size):
                batch = tokenizer.pad(chunks[start:start + batch_size], padding=True, return_tensors="pt")
                rows = model(**batch).logits.softmax(-1).tolist()
                for j, row in enumerate(rows, start):
                    owner, weight = owners[j], weights[j]
                    denominators[owner] += weight
                    counts[owner] += 1
                    for k, value in enumerate(row):
                        totals[owner][k] += value * weight
        results = []
        for i in range(len(texts)):
            if not denominators[i]:
                results.append({"label": None, "scores": {}, "chunk_count": 0})
                continue
            scores = dict(zip(labels, (v / denominators[i] for v in totals[i])))
            results.append({"label": max(scores, key=scores.get), "scores": scores, "chunk_count": counts[i]})
        return results


class TransformerSentimentAnalyzer:
    def __init__(self, model_name, batch_size):
        self.model_name = model_name
        self.batch_size = batch_size

    def classify(self, texts):
        return classify(texts, self.model_name, self.batch_size)

    def describe(self):
        return {"model": self.model_name, "language": "en"}
