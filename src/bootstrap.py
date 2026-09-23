from config.settings import get_settings
from adapters.gemini_recommendations import GeminiRecommendationGenerator
from adapters.transformer_sentiment import TransformerSentimentAnalyzer
from adapters.semantic_grouping import SemanticComplaintGrouper
from adapters.keyphrase_extraction import SpacyKeyBERTExtractor
from review_analysis.service import ReviewAnalysisService


@lru_cache(maxsize=1)
def get_review_analysis():
    settings = get_settings()
    generator = GeminiRecommendationGenerator(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout=settings.gemini_timeout,
        max_output_tokens=settings.gemini_max_output_tokens,
        evidence_limit=settings.gemini_evidence_limit,
        quote_limit=settings.gemini_quote_limit,
    ) if settings.gemini_api_key else None
    return ReviewAnalysisService(
        sentiment=TransformerSentimentAnalyzer(settings.sentiment_model, settings.sentiment_batch_size),
        grouping=SemanticComplaintGrouper(settings.embedding_model, settings.topic_distance_threshold,
                                           settings.topic_merge_threshold),
        keyphrases=SpacyKeyBERTExtractor(
            settings.spacy_model,
            settings.embedding_model,
            settings.keyphrase_per_review_limit,
            settings.keyword_limit,
            settings.keyword_min_review_count,
        ),
        recommendations=generator,
        recommendation_topic_limit=settings.recommendation_topic_limit,
    )
from functools import lru_cache
