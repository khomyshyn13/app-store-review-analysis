import argparse
import json
from pathlib import Path

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from adapters.transformer_sentiment import TransformerSentimentAnalyzer
from config.settings import get_settings


def load_jsonl(path):
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("label") not in {"positive", "neutral", "negative"} or not isinstance(row.get("text"), str):
            raise ValueError(f"Invalid validation record at line {number}")
        rows.append(row)
    if not rows:
        raise ValueError("Validation set is empty")
    return rows


def evaluate(rows, analyzer):
    expected = [row["label"] for row in rows]
    predictions = analyzer.classify([row["text"] for row in rows])
    actual = [item["label"] for item in predictions]
    labels = ["negative", "neutral", "positive"]
    return {
        "sample_count": len(rows),
        "model": analyzer.describe(),
        "accuracy": round(accuracy_score(expected, actual), 4),
        "macro_f1": round(f1_score(expected, actual, labels=labels, average="macro", zero_division=0), 4),
        "per_class": classification_report(expected, actual, labels=labels, output_dict=True, zero_division=0),
        "confusion_matrix": {"labels": labels, "values": confusion_matrix(expected, actual, labels=labels).tolist()},
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate sentiment on a labeled App Store JSONL set")
    parser.add_argument("validation_set", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    result = evaluate(load_jsonl(args.validation_set), TransformerSentimentAnalyzer(
        settings.sentiment_model, settings.sentiment_batch_size
    ))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
