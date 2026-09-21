from functools import lru_cache


@lru_cache(maxsize=1)
def get_encoder(model_name):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_name, device="cpu")


class SemanticComplaintGrouper:
    def __init__(self, model_name, distance_threshold):
        self.model_name = model_name
        self.distance_threshold = distance_threshold

    def describe(self):
        return {"model": self.model_name, "linkage": "complete",
                "cosine_distance_threshold": self.distance_threshold}

    def group(self, texts):
        if not texts:
            return []
        import numpy as np
        from sklearn.cluster import AgglomerativeClustering
        vectors = get_encoder(self.model_name).encode(texts, normalize_embeddings=True)
        labels = (AgglomerativeClustering(
            n_clusters=None, metric="cosine", linkage="complete",
            distance_threshold=self.distance_threshold).fit_predict(vectors)
            if len(texts) > 1 else [0])
        groups = {}
        for i, label in enumerate(labels):
            groups.setdefault(int(label), []).append(i)
        result = []
        for indices in groups.values():
            centroid = np.mean(vectors[indices], axis=0)
            result.append(sorted(indices, key=lambda i: -float(vectors[i] @ centroid)))
        return result
