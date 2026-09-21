# App Store Review Analysis

## Quick start

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m spacy download en_core_web_sm
cp .env.example .env
```

```sh
venv/bin/python -m uvicorn api.app:app --app-dir src --reload
```

Frontend will be avaible here: http://127.0.0.1:8000
Backend API: http://127.0.0.1:8000/docs


## Structure

```text
src/
  api/app.py                       HTTP, requests validations
  api/static/                      simple frontend with vanila HTML, CSS 
  bootstrap.py                     connects adapters
  config/settings.py               configurations and settings
  collection/collector.py          Apple Search API + RSS/JSON reviews
  processing/preprocessing.py      data cleaning and preprocessing
  analytics/
    metrics.py                     average rating and star distribution
    reporting.py                   Markdown from reports
    visualizations.py              PNG graphics from reports
  review_analysis/
    ports.py                       Protocol interfaces RecommendationError
    service.py                     business logic and answers validation
    topics.py                      complaints, evidence, and calculations by topic
  adapters/
    transformer_sentiment.py       local Transformers sentiment
    semantic_grouping.py           Sentence Transformers + sklearn
    keyphrase_extraction.py        spaCy candidates + KeyBERT + frequencies
    gemini_recommendations.py      Gemini HTTP, prompt, JSON schema, repeat
```

## Як працює аналіз

### 1. Collection

The Apple Search API retrieves the ID based on the name. The public feed returns the latest reviews
for the selected storefront. We crawl up to 10 pages, remove duplicates by ID, and randomly
select a specific `count` of unique items from this pool. A seed reproduces the sample only if
the pool remains identical. This is NOT a random sample of the entire App Store history.

If fewer than `count` reviews are available, we return the available ones with `sample_complete=false`.
A duplicate or empty page does not halt the crawl; the public Apple feed sometimes returns empty pages
between populated ones. All pages up to `max_pages` are checked, and the number of empty pages
is recorded in metadata and warnings. Missing IDs, text, or ratings (1–5) result in the record
being excluded from the explicit count. Missing titles or dates are permissible. The public feed is subject to change.

### 2. Preprocessing

Original fields are preserved. Fields `clean_title`, `clean_text`, `nlp_text`, and `nlp_usable` are added.
Processing includes Unicode NFC normalization, removal of common HTML tags, entity decoding,
and whitespace cleanup. Case, negation, punctuation, emojis, and URLs are preserved.
Ratings are not passed to the models. Empty texts are retained for rating statistics.

### 3. Statistics

The average and the 1–5 distribution are calculated based on valid ratings. Missing ratings
are excluded from the denominator and tracked separately. Invalid values ​​trigger an error.
If there are no ratings, the average and percentages are null, and counts are zero. Percentages are rounded to two decimal places.

### 4. Recommendations

- **Sentiment:** `cardiffnlp/twitter-roberta-base-sentiment-latest`, English,
positive/negative/neutral. CPU batch inference. Long reviews are split into token blocks; 
scores are averaged based on their length. Softmax does not represent calibrated confidence.
- **Phrases:** spaCy performs POS/dependency parsing and generates noun and verb
phrase candidates. KeyBERT ranks candidates based on their semantic proximity to the review content. 
Python aggregates word forms via lemmas and counts unique negative reviews. 
Phrases appearing in at least 2 reviews are returned, up to a maximum of 30 results. The `relevance_score`
determines the order only after `review_count`; it represents neither frequency nor probability.
- **Topics:** negative sentences from all reviews; MiniLM embeddings and agglomerative
clustering (complete linkage, cosine distance 0.45). Single-item clusters are retained. 
Citations include `review_id`, `evidence_id`, and positions within the `nlp_text`. A single review may
span multiple topics, so their shares do not necessarily sum to 100%.
- **Recommendations:** up to 10 topics with the highest number of unique reviews; up to 3 citations
per topic, with a limit of 1,200 characters per citation. A single Gemini request (excluding retries upon failure). 
Returns the title, observation, action, verification, and `evidence_ids` in Ukrainian. 
Volume constraints reduce costs; all identified topics remain in the report. 
Numerical calculations are performed by Python. The response is validated for structure,
coverage of selected topics, and the relevance of the supporting evidence. 
Review text is marked as untrusted data within the prompt.

### Visualizations

- `rating_distribution.png`: count and proportion of ratings (1–5).
- `sentiment_distribution.png`: negative/neutral/positive sentiment based on review text.
- `top_issues.png`: up to 10 most common complaint topics by number of unique reviews. 
If Gemini processing succeeds, short recommendation titles are used; 
otherwise, representative quotes are used. Individual topics are displayed only when
there are no topics with two or more reviews.