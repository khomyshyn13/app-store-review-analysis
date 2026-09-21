import argparse
import html
import json
from pathlib import Path
import re
import sys
import unicodedata


def clean_text(text):
    if text is None:
        return ""
    if not isinstance(text, str):
        raise ValueError("Review title and text must be strings or null")
    text = re.sub(r"</?(?:p|br|div|span|b|i|strong|em|a|ul|ol|li)\b[^>]*>",
                  " ", text, flags=re.IGNORECASE)
    text = html.unescape(text)
    text = unicodedata.normalize("NFC", text)
    text = "".join(" " if unicodedata.category(char) == "Cc" else char for char in text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return " ".join(text.split())


def preprocess_reviews(data):
    if not isinstance(data, dict) or not isinstance(data.get("reviews"), list):
        raise ValueError("Input must contain a 'reviews' array")
    prepared, seen_ids = [], set()
    for index, review in enumerate(data["reviews"]):
        if not isinstance(review, dict):
            raise ValueError(f"Review at index {index} must be an object")
        review_id = review.get("id")
        if not isinstance(review_id, str) or not review_id.strip():
            raise ValueError(f"Review at index {index} has a missing/invalid ID")
        if review_id in seen_ids:
            raise ValueError(f"Duplicate review ID: {review_id}")
        seen_ids.add(review_id)
        title, text = clean_text(review.get("title")), clean_text(review.get("text"))
        nlp_text = "\n".join(part for part in (title, text if text != title else "") if part)
        prepared.append({**review, "clean_title": title, "clean_text": text,
                         "nlp_text": nlp_text, "nlp_usable": bool(nlp_text)})
    return {**data, "reviews": prepared, "preprocessing": {
        "version": 1,
        "review_count": len(prepared),
        "usable_count": sum(review["nlp_usable"] for review in prepared),
        "empty_count": sum(not review["nlp_usable"] for review in prepared),
    }}


def main():
    parser = argparse.ArgumentParser(description="Prepare collected review text for NLP")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/reviews_prepared.json"))
    args = parser.parse_args()
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Choose a different output path to preserve the original file")
        data = json.loads(args.input.read_text(encoding="utf-8"))
        result = preprocess_reviews(data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    stats = result["preprocessing"]
    print(f"Prepared {stats['usable_count']}/{stats['review_count']} reviews → {args.output}")
    if stats["empty_count"]:
        print(f"Warning: {stats['empty_count']} reviews have no usable text; retained with nlp_usable=false",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
