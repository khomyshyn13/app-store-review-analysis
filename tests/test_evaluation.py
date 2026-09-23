from evaluation.sentiment import evaluate


class Analyzer:
    def classify(self, texts):
        return [{"label": label} for label in ("negative", "positive", "positive")]

    def describe(self):
        return {"model": "fixture", "language": "multilingual"}


def test_evaluation_reports_accuracy_and_macro_f1():
    rows = [
        {"text": "bad", "label": "negative"},
        {"text": "fine", "label": "neutral"},
        {"text": "great", "label": "positive"},
    ]
    result = evaluate(rows, Analyzer())
    assert result["accuracy"] == 0.6667
    assert result["sample_count"] == 3
    assert result["confusion_matrix"]["labels"] == ["negative", "neutral", "positive"]
