import json
import random
import re
import ssl
import time
import certifi
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode


class CollectionError(Exception):
    """An expected source/network error, suitable for displaying to the user"""


def _fetch_json(url):
    context = ssl.create_default_context(cafile=certifi.where())
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "ReviewCollector/0.1"})
            with urlopen(request, timeout=20, context=context) as response:
                data = json.load(response)
            return data
        except HTTPError as exc:
            if exc.code == 404:
                raise CollectionError(
                    "Apple resource not found: check the app and country"
                ) from exc
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise CollectionError(f"Apple returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if isinstance(getattr(exc, "reason", exc), ssl.SSLCertVerificationError):
                raise CollectionError(
                    "TLS certificate verification failed. Update certifi with "
                    "'python -m pip install --upgrade certifi'. If using a corporate "
                    "proxy, check its trusted certificates; certificate verification remains enabled."
                ) from exc
            if attempt == 2:
                raise CollectionError(f"Could not connect to Apple ({exc})") from exc
        except (ValueError, UnicodeError) as exc:
            raise CollectionError("Apple returned invalid JSON") from exc
        time.sleep(2 ** attempt)


def search_apps(name, country="us"):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("App name must not be empty")
    if not isinstance(country, str) or not re.fullmatch(r"[a-zA-Z]{2}", country):
        raise ValueError("country must be a two-letter storefront code, e.g. us")
    query = urlencode({"term": name.strip(), "country": country.lower(),
                       "media": "software", "entity": "software", "limit": 20})
    data = _fetch_json("https://itunes.apple.com/search?" + query)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise CollectionError("Apple returned an invalid search response")
    apps = {}
    for row in data["results"]:
        if not isinstance(row, dict):
            continue
        app_id, title = row.get("trackId"), row.get("trackName")
        if type(app_id) is not int or app_id <= 0 or not isinstance(title, str) or not title.strip():
            continue
        apps[app_id] = {"id": str(app_id), "name": title,
                        "developer": row.get("artistName") or "Unknown developer"}
    if not apps:
        raise CollectionError(f"No apps found for {name!r} in storefront {country}")
    return list(apps.values())


def _fetch_page(app_id, country, page):
    url = (f"https://itunes.apple.com/{country}/rss/customerreviews/"
           f"page={page}/id={app_id}/sortby=mostrecent/json")
    data = _fetch_json(url)
    if not isinstance(data, dict) or not isinstance(data.get("feed"), dict):
        raise CollectionError(f"Page {page}: unexpected response format")
    entries = data["feed"].get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise CollectionError(f"Page {page}: invalid review list")
    return entries


def _parse_review(entry):
    if not isinstance(entry, dict):
        return None

    def label(key):
        field = entry.get(key)
        value = field.get("label") if isinstance(field, dict) else None
        return value.strip() if isinstance(value, str) else ""

    review_id, text = label("id"), label("content")
    rating = label("im:rating")
    if not review_id or not text or rating not in {"1", "2", "3", "4", "5"}:
        return None
    return {
        "id": review_id,
        "title": label("title"),
        "text": text,
        "rating": int(rating),
        "updated_at": label("updated") or None,
    }


def collect_reviews(app_id, country="us", count=100, seed=42, max_pages=10):
    app_id = str(app_id).strip()
    if not re.fullmatch(r"[0-9]+", app_id) or int(app_id) == 0:
        raise ValueError("app_id must be a positive numeric App Store ID")
    if not isinstance(country, str) or not re.fullmatch(r"[a-zA-Z]{2}", country):
        raise ValueError("country must be a two-letter storefront code, e.g. us")
    if type(count) is not int or not 1 <= count <= 500:
        raise ValueError("count must be between 1 and 500")
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise ValueError("max_pages must be between 1 and 10")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    country = country.lower()
    pool, warnings = {}, []
    skipped = duplicates = pages_fetched = empty_pages = repeated_pages = 0
    stop_reason = "page_limit"

    for page in range(1, max_pages + 1):
        try:
            entries = _fetch_page(app_id, country, page)
        except CollectionError as exc:
            if not pool:
                raise
            warnings.append(str(exc))
            stop_reason = "source_error"
            break
        pages_fetched += 1
        if not entries:
            empty_pages += 1
            continue
        added = valid = 0
        for entry in entries:
            review = _parse_review(entry)
            if review is None:
                skipped += 1
                continue
            valid += 1
            if review["id"] in pool:
                duplicates += 1
                continue
            pool[review["id"]] = review
            added += 1
        if valid and not added:
            repeated_pages += 1
            continue
        if page < max_pages:
            time.sleep(0.3)

    if not pool:
        raise CollectionError(
            f"Apple returned no usable reviews across {pages_fetched} feed pages. "
            "Try another storefront or retry later; the public review feed can "
            "temporarily return empty pages."
        )
    if skipped:
        warnings.append(f"Skipped {skipped} entries with missing/invalid ID, text or rating")
    if len(pool) < count:
        warnings.append(f"Requested {count} reviews, but only {len(pool)} unique reviews are available")
    if empty_pages:
        warnings.append(
            f"Apple returned {empty_pages} empty feed pages; collection continued through the remaining pages"
        )
    if repeated_pages:
        warnings.append(
            f"Apple returned {repeated_pages} repeated feed pages; duplicate reviews were ignored"
        )

    candidates = sorted(pool.values(), key=lambda review: review["id"])
    sample = random.Random(seed).sample(candidates, min(count, len(candidates)))
    return {
        "app_id": app_id,
        "country": country,
        "requested_count": count,
        "collected_count": len(sample),
        "pool_size": len(pool),
        "sample_complete": len(sample) == count,
        "pages_fetched": pages_fetched,
        "empty_pages": empty_pages,
        "repeated_pages": repeated_pages,
        "stop_reason": stop_reason,
        "skipped_entries": skipped,
        "duplicate_entries": duplicates,
        "seed": seed,
        "sampling_scope": "accessible recent reviews in the selected storefront",
        "warnings": warnings,
        "reviews": sample,
    }
