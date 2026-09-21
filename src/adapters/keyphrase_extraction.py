from collections import defaultdict
from functools import lru_cache


@lru_cache(maxsize=4)
def _load_spacy(model_name):
    import spacy
    return spacy.load(model_name, disable=["ner"])


@lru_cache(maxsize=4)
def _load_keybert(model_name):
    from keybert import KeyBERT
    from .semantic_grouping import get_encoder
    return KeyBERT(model=get_encoder(model_name))


def _normalize(span):
    values = []
    for token in span:
        if token.is_punct or token.is_space or token.pos_ == "DET":
            continue
        value = token.lemma_.lower().strip()
        if value:
            values.append(value)
    return " ".join(values)


def _noun_candidates(doc):
    for chunk in doc.noun_chunks:
        content = [token for token in chunk if token.pos_ in {"NOUN", "PROPN", "ADJ", "NUM"}]
        if any(token.pos_ in {"NOUN", "PROPN"} for token in content):
            start = min(token.i for token in content)
            end = max(token.i for token in content) + 1
            yield doc[start:end]


def _verb_candidates(doc):
    for token in doc:
        if token.pos_ != "VERB":
            continue
        related = [token]
        prepositions = []
        for child in token.children:
            if child.dep_ in {"aux", "auxpass", "neg", "prt", "dobj", "obj", "attr", "oprd"}:
                related.extend(list(child.subtree))
            elif child.dep_ in {"xcomp", "ccomp"}:
                related.append(child)
                for nested in child.children:
                    if nested.dep_ in {"aux", "auxpass", "neg", "prt", "dobj", "obj", "attr", "oprd"}:
                        related.extend(list(nested.subtree))
            elif child.dep_ in {"prep"}:
                prepositions.extend(list(child.subtree))
        variants = [related]
        if prepositions:
            variants.append([*related, *prepositions])
        for variant in variants:
            start = min(item.i for item in variant)
            end = max(item.i for item in variant) + 1
            span = doc[start:end]
            if len([item for item in span if not item.is_punct and not item.is_space]) >= 2:
                yield span


def _candidates(doc):
    result = {}
    for span in [*_noun_candidates(doc), *_verb_candidates(doc)]:
        text = span.text.strip(" \t\n,.;:!?-–—")
        normalized = _normalize(span)
        if text and normalized and normalized not in result:
            result[normalized] = text
    return result


class SpacyKeyBERTExtractor:
    def __init__(self, spacy_model, embedding_model, per_review_limit, result_limit,
                 min_review_count):
        self.spacy_model = spacy_model
        self.embedding_model = embedding_model
        self.per_review_limit = per_review_limit
        self.result_limit = result_limit
        self.min_review_count = min_review_count

    def extract(self, reviews, sentiments):
        negative_ids = {item["review_id"] for item in sentiments if item["label"] == "negative"}
        negative_reviews = [review for review in reviews if review["id"] in negative_ids]
        if not negative_reviews:
            return self._result(0, [])
        nlp = _load_spacy(self.spacy_model)
        ranker = _load_keybert(self.embedding_model)
        aggregated = defaultdict(lambda: {"review_ids": set(), "scores": [], "examples": []})
        for review, doc in zip(negative_reviews,
                               nlp.pipe((item["nlp_text"] for item in negative_reviews), batch_size=32)):
            candidates = _candidates(doc)
            if not candidates:
                continue
            display_to_normalized = {display.casefold(): normalized for normalized, display in candidates.items()}
            ranked = ranker.extract_keywords(
                review["nlp_text"],
                candidates=list(display_to_normalized),
                keyphrase_ngram_range=(1, max(len(value.split()) for value in display_to_normalized)),
                top_n=min(self.per_review_limit, len(display_to_normalized)),
                use_mmr=True,
                diversity=0.35,
            )
            for phrase, score in ranked:
                normalized = display_to_normalized.get(phrase.casefold())
                if normalized is None:
                    continue
                item = aggregated[normalized]
                item["review_ids"].add(review["id"])
                item["scores"].append(float(score))
                if len(item["examples"]) < 3:
                    item["examples"].append({"review_id": review["id"],
                                             "phrase": candidates[normalized]})
        rows = []
        for normalized, item in aggregated.items():
            count = len(item["review_ids"])
            if count < self.min_review_count:
                continue
            rows.append({
                "phrase": item["examples"][0]["phrase"],
                "normalized_phrase": normalized,
                "review_count": count,
                "percentage": round(100 * count / len(negative_reviews), 2),
                "relevance_score": round(sum(item["scores"]) / len(item["scores"]), 4),
                "review_ids": sorted(item["review_ids"]),
                "examples": item["examples"],
            })
        rows.sort(key=lambda item: (-item["review_count"], -item["relevance_score"],
                                    item["normalized_phrase"]))
        return self._result(len(negative_reviews), rows[:self.result_limit])

    def _result(self, negative_count, phrases):
        return {
            "method": "spaCy grammatical candidates + KeyBERT ranking + document frequency",
            "spacy_model": self.spacy_model,
            "embedding_model": self.embedding_model,
            "negative_review_count": negative_count,
            "min_review_count": self.min_review_count,
            "phrases": phrases,
        }
