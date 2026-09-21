import argparse
from collections import Counter
import json
from pathlib import Path
import sys


def calculate_metrics(data):
    if not isinstance(data, dict) or not isinstance(data.get("reviews"), list):
        raise ValueError("Input must contain a 'reviews' array")
    counts = Counter()
    missing = 0
    for index, review in enumerate(data["reviews"]):
        if not isinstance(review, dict):
            raise ValueError(f"Review at index {index} must be an object")
        rating = review.get("rating")
        if rating is None:
            missing += 1
            continue
        if type(rating) is not int or not 1 <= rating <= 5:
            raise ValueError(f"Review at index {index}: rating must be an integer from 1 to 5")
        counts[rating] += 1

    rated_count = sum(counts.values())
    return {
        "review_count": len(data["reviews"]),
        "rated_review_count": rated_count,
        "missing_rating_count": missing,
        "average_rating": (
            sum(rating * count for rating, count in counts.items()) / rated_count
            if rated_count else None
        ),
        "rating_distribution": {
            str(rating): {
                "count": counts[rating],
                "percentage": round(counts[rating] / rated_count * 100, 2) if rated_count else None,
            }
            for rating in range(1, 6)
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Calculate app review rating statistics")
    parser.add_argument("input", type=Path, help="Collected or preprocessed reviews JSON")
    parser.add_argument("--output", type=Path, default=Path("data/metrics.json"))
    args = parser.parse_args()
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Choose a different output path to preserve the reviews")
        data = json.loads(args.input.read_text(encoding="utf-8"))
        metrics = calculate_metrics(data)
        result = {key: data[key] for key in ("app_id", "app_name", "country", "collected_at")
                  if key in data}
        result["metrics"] = metrics
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    average = metrics["average_rating"]
    print(f"Average rating: {average:.2f}/5" if average is not None else "Average rating: unavailable")
    for rating, values in metrics["rating_distribution"].items():
        percentage = values["percentage"]
        share = f"{percentage:.2f}%" if percentage is not None else "unavailable"
        print(f"{rating} stars: {values['count']} ({share})")
    if metrics["missing_rating_count"]:
        print(f"Warning: {metrics['missing_rating_count']} reviews have no rating; "
              "excluded from the average and percentage denominator", file=sys.stderr)
    print(f"Saved metrics → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
