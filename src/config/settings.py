from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = ROOT_DIR / "data" / "collections"
    model_cache_dir: Path = ROOT_DIR / ".cache" / "huggingface"
    matplotlib_cache_dir: Path = ROOT_DIR / ".cache" / "matplotlib"
    sentiment_model: str = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    spacy_model: str = "en_core_web_sm"
    sentiment_batch_size: int = 16
    topic_distance_threshold: float = 0.45
    topic_merge_threshold: float = 0.58
    keyword_limit: int = 30
    keyphrase_per_review_limit: int = 8
    keyword_min_review_count: int = 2
    recommendation_topic_limit: int = 10
    visualization_topic_limit: int = 10
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout: int = 60
    gemini_max_output_tokens: int = 8192
    gemini_evidence_limit: int = 3
    gemini_quote_limit: int = 1200
    gemini_api_key: str = field(default="", repr=False)
    warmup_models: bool = True

    def __post_init__(self):
        for name in ("sentiment_batch_size", "keyword_limit", "keyphrase_per_review_limit",
                     "keyword_min_review_count", "recommendation_topic_limit",
                     "visualization_topic_limit",
                     "gemini_timeout", "gemini_max_output_tokens", "gemini_evidence_limit", "gemini_quote_limit"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not 0 < self.topic_distance_threshold <= 2:
            raise ValueError("topic_distance_threshold must be between 0 (exclusive) and 2")
        if not self.topic_distance_threshold <= self.topic_merge_threshold <= 2:
            raise ValueError("topic_merge_threshold must be at least topic_distance_threshold and at most 2")


@lru_cache(maxsize=1)
def get_settings():
    load_dotenv(ROOT_DIR / ".env", override=False)
    settings = Settings(
        data_dir=Path(os.getenv("APP_DATA_DIR", str(Settings.data_dir))).expanduser(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", Settings.gemini_model).strip(),
        sentiment_model=os.getenv("SENTIMENT_MODEL", Settings.sentiment_model).strip(),
        embedding_model=os.getenv("EMBEDDING_MODEL", Settings.embedding_model).strip(),
        warmup_models=os.getenv("WARMUP_MODELS", "true").strip().lower() not in {"0", "false", "no"},
    )
    os.environ.setdefault("HF_HOME", str(settings.model_cache_dir))
    os.environ.setdefault("MPLCONFIGDIR", str(settings.matplotlib_cache_dir))
    return settings
