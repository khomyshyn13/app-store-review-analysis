from functools import lru_cache


@lru_cache(maxsize=1)
def get_encoder(model_name):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_name, device="cpu")


class SemanticComplaintGrouper:
    def __init__(self, model_name, distance_threshold, merge_threshold=None):
        self.model_name = model_name
        self.distance_threshold = distance_threshold
        self.merge_threshold = merge_threshold or distance_threshold

    def describe(self):
        return {"model": self.model_name, "linkage": "complete",
                "cosine_distance_threshold": self.distance_threshold,
                "small_cluster_merge_threshold": self.merge_threshold}

    def warmup(self):
        get_encoder(self.model_name)

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
        grouped = list(groups.values())
        large = [indices for indices in grouped if len(indices) > 1]
        small = [indices[0] for indices in grouped if len(indices) == 1]
        for index in small:
            if not large:
                large.append([index])
                continue
            centroids = [np.mean(vectors[indices], axis=0) for indices in large]
            similarities = [float(vectors[index] @ centroid) for centroid in centroids]
            target = int(np.argmax(similarities))
            if 1 - similarities[target] <= self.merge_threshold:
                large[target].append(index)
            else:
                large.append([index])
        result = []
        for indices in large:
            centroid = np.mean(vectors[indices], axis=0)
            result.append(sorted(indices, key=lambda i: -float(vectors[i] @ centroid)))
        return result
