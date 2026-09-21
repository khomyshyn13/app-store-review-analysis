from io import BytesIO
from pathlib import Path
import textwrap

from config.settings import get_settings

get_settings()
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


COLORS = {
    "blue": "#3772FF",
    "green": "#2FB344",
    "gray": "#868E96",
    "red": "#E03131",
    "orange": "#F08C00",
}


def _save(figure, path):
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    temporary = path.with_suffix(".png.tmp")
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(path)


def _figure(title, height=5):
    figure, axis = plt.subplots(figsize=(9, height))
    figure.suptitle(title, fontsize=16, fontweight="bold")
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(axis="y", alpha=0.2)
    axis.set_axisbelow(True)
    return figure, axis


def _rating_distribution(collection, path):
    distribution = collection["metrics"]["rating_distribution"]
    ratings = list(range(1, 6))
    counts = [distribution[str(rating)]["count"] for rating in ratings]
    percentages = [distribution[str(rating)]["percentage"] for rating in ratings]
    figure, axis = _figure("Rating distribution")
    bars = axis.bar(ratings, counts, color=COLORS["blue"], width=0.65)
    axis.set_xlabel("Stars")
    axis.set_ylabel("Reviews")
    axis.set_xticks(ratings)
    axis.set_ylim(0, max(counts or [0]) * 1.18 + 1)
    for bar, count, percentage in zip(bars, counts, percentages):
        label = f"{count}\n{percentage:.1f}%" if percentage is not None else str(count)
        axis.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), label,
                  ha="center", va="bottom", fontsize=10)
    _save(figure, path)


def _sentiment_distribution(collection, path):
    counts_by_label = collection["insights"]["sentiment"]["counts"]
    labels = ["negative", "neutral", "positive"]
    counts = [counts_by_label[label] for label in labels]
    total = sum(counts)
    figure, axis = _figure("Sentiment distribution")
    bars = axis.bar(labels, counts, color=[COLORS["red"], COLORS["gray"], COLORS["green"]],
                    width=0.65)
    axis.set_ylabel("Reviews")
    axis.set_ylim(0, max(counts or [0]) * 1.18 + 1)
    for bar, count in zip(bars, counts):
        percentage = 100 * count / total if total else 0
        axis.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                  f"{count}\n{percentage:.1f}%", ha="center", va="bottom", fontsize=10)
    _save(figure, path)


def _topic_label(topic, recommendations):
    recommendation = recommendations.get(topic["topic_id"])
    value = recommendation["title"] if recommendation else topic["representative_quote"]
    value = " ".join(value.split())
    if len(value) > 70:
        value = value[:67].rstrip() + "..."
    return "\n".join(textwrap.wrap(value, width=38))


def _top_issues(collection, path, limit):
    insights = collection["insights"]
    recommendations = {item["topic_id"]: item
                       for item in insights.get("recommendations", {}).get("items", [])}
    topics = [topic for topic in insights.get("topics", []) if topic["review_count"] >= 2][:limit]
    if not topics:
        topics = insights.get("topics", [])[:limit]
    figure, axis = _figure("Most common complaint themes", height=max(5, 0.62 * len(topics) + 2))
    if not topics:
        axis.axis("off")
        axis.text(0.5, 0.5, "No complaint themes found", ha="center", va="center", fontsize=14)
        _save(figure, path)
        return
    topics = list(reversed(topics))
    labels = [_topic_label(topic, recommendations) for topic in topics]
    counts = [topic["review_count"] for topic in topics]
    bars = axis.barh(labels, counts, color=COLORS["orange"], height=0.62)
    axis.set_xlabel("Unique reviews")
    axis.grid(axis="x", alpha=0.2)
    axis.grid(axis="y", visible=False)
    axis.set_xlim(0, max(counts) * 1.2 + 0.5)
    for bar, topic in zip(bars, topics):
        axis.text(bar.get_width(), bar.get_y() + bar.get_height() / 2,
                  f" {topic['review_count']} ({topic['percentage']:.1f}%)",
                  va="center", fontsize=10)
    _save(figure, path)


def create_visualizations(collection, folder, topic_limit=10):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    generated = {}
    rating_path = folder / "rating_distribution.png"
    _rating_distribution(collection, rating_path)
    generated["rating_distribution"] = rating_path.name
    if "sentiment" in collection.get("insights", {}):
        sentiment_path = folder / "sentiment_distribution.png"
        issues_path = folder / "top_issues.png"
        _sentiment_distribution(collection, sentiment_path)
        _top_issues(collection, issues_path, topic_limit)
        generated["sentiment_distribution"] = sentiment_path.name
        generated["top_issues"] = issues_path.name
    return generated
