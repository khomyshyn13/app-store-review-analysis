const state = {
  candidates: [],
  selected: null,
  collection: null,
  reviews: [],
  visibleReviews: 10
};

const byId = id => document.getElementById(id);
const searchForm = byId("search-form");
const resultsSection = byId("results-section");
const candidateGrid = byId("candidate-grid");
const collectButton = byId("collect-button");
const dashboard = byId("dashboard");
const loading = byId("loading");
const toast = byId("toast");

function setLoading(active, title = "Working on it", copy = "This can take a moment.") {
  byId("loading-title").textContent = title;
  byId("loading-copy").textContent = copy;
  loading.classList.toggle("hidden", !active);
}

function showError(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  window.clearTimeout(showError.timer);
  showError.timer = window.setTimeout(() => toast.classList.add("hidden"), 6000);
}

async function request(url, options) {
  const response = await fetch(url, options);
  if (response.ok) return response.json();
  let message = `Request failed with status ${response.status}`;
  try {
    const body = await response.json();
    const detail = body.detail;
    message = typeof detail === "string" ? detail : detail?.message || message;
  } catch (_) {
    message = response.statusText || message;
  }
  throw new Error(message);
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderCandidates() {
  candidateGrid.replaceChildren();
  state.candidates.slice(0, 9).forEach(app => {
    const button = makeElement("button", "candidate");
    button.type = "button";
    button.append(
      makeElement("div", "candidate-name", app.name),
      makeElement("div", "candidate-developer", app.developer),
      makeElement("div", "candidate-id", `App Store ID · ${app.id}`)
    );
    button.addEventListener("click", () => {
      state.selected = app;
      document.querySelectorAll(".candidate").forEach(item => item.classList.remove("selected"));
      button.classList.add("selected");
      collectButton.disabled = false;
    });
    candidateGrid.append(button);
  });
  resultsSection.classList.remove("hidden");
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

searchForm.addEventListener("submit", async event => {
  event.preventDefault();
  const name = byId("app-name").value.trim();
  const country = byId("country").value;
  if (!name) return;
  setLoading(true, "Searching the App Store", "Finding matching applications and developers.");
  try {
    const data = await request(`/apps/search?name=${encodeURIComponent(name)}&country=${encodeURIComponent(country)}`);
    state.candidates = data.apps;
    state.selected = null;
    collectButton.disabled = true;
    renderCandidates();
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false);
  }
});

collectButton.addEventListener("click", async () => {
  if (!state.selected) return;
  const count = Number(byId("review-count").value);
  if (!Number.isInteger(count) || count < 1 || count > 500) {
    showError("Review count must be between 1 and 500.");
    return;
  }
  setLoading(true, "Collecting reviews", "Reading recent reviews and preparing rating metrics.");
  try {
    const body = {
      app_name: state.selected.name,
      app_id: state.selected.id,
      country: byId("country").value,
      count,
      seed: 42,
      max_pages: 10
    };
    state.collection = await request("/collections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    await loadReviews();
    renderDashboard();
    dashboard.classList.remove("hidden");
    dashboard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false);
  }
});

async function loadReviews() {
  const response = await fetch(state.collection.download_url);
  if (!response.ok) throw new Error("The collection was created, but reviews could not be loaded.");
  const raw = await response.json();
  state.reviews = Array.isArray(raw.reviews) ? raw.reviews : [];
  state.visibleReviews = 10;
}

function renderDashboard() {
  const collection = state.collection;
  byId("dashboard-title").textContent = collection.app_name;
  byId("dashboard-meta").textContent = `${collection.developer} · ${collection.country.toUpperCase()} storefront · ${collection.collected_count} reviews`;
  byId("raw-download").href = collection.download_url;
  byId("report-download").href = `/collections/${collection.collection_id}/report/download`;
  byId("report-download").classList.remove("hidden");
  renderWarnings();
  renderStats();
  renderCharts();
  renderInsights();
  renderReviews();
}

function renderWarnings() {
  const box = byId("warning-box");
  const warnings = state.collection.warnings || [];
  box.textContent = warnings.join(" ");
  box.classList.toggle("hidden", warnings.length === 0);
}

function renderStats() {
  const metrics = state.collection.metrics;
  const negative = state.collection.insights?.sentiment?.counts?.negative;
  const cards = [
    ["Average rating", metrics.average_rating === null ? "N/A" : `${metrics.average_rating.toFixed(2)} / 5`, "Across rated reviews"],
    ["Reviews collected", metrics.review_count, `${state.collection.pool_size} available in source pool`],
    ["5-star reviews", `${metrics.rating_distribution["5"].percentage ?? 0}%`, `${metrics.rating_distribution["5"].count} reviews`],
    ["Negative sentiment", negative === undefined ? "Pending" : `${Math.round(negative / Math.max(metrics.review_count, 1) * 100)}%`, negative === undefined ? "Run AI analysis to calculate" : `${negative} reviews`]
  ];
  const grid = byId("stat-grid");
  grid.replaceChildren(...cards.map(([label, value, detail]) => {
    const card = makeElement("article", "stat-card");
    card.append(makeElement("div", "stat-label", label), makeElement("div", "stat-value", value), makeElement("div", "stat-detail", detail));
    return card;
  }));
}

function renderCharts() {
  const labels = {
    rating_distribution: "Rating distribution",
    sentiment_distribution: "Sentiment distribution"
  };
  const grid = byId("chart-grid");
  grid.replaceChildren();
  Object.entries(state.collection.visualizations || {}).forEach(([name, url]) => {
    if (!(name in labels)) return;
    const card = makeElement("article", "chart-card");
    const image = document.createElement("img");
    image.src = `${url}?v=${Date.now()}`;
    image.alt = labels[name] || name;
    card.append(image);
    grid.append(card);
  });
}

function renderInsights() {
  const insights = state.collection.insights || {};
  const analyzed = Boolean(insights.sentiment);
  const recommendationItems = insights.recommendations?.items || [];
  const status = byId("analysis-status");
  status.textContent = analyzed ? (insights.status === "completed" ? "Analysis complete" : "Analysis partially complete") : "Awaiting analysis";
  status.classList.toggle("ready", analyzed);
  byId("insights-section").classList.toggle("hidden", !analyzed);
  byId("recommendations-section").classList.toggle("hidden", !analyzed || recommendationItems.length === 0);
  byId("analyze-button").textContent = analyzed ? "Run analysis again" : "Run AI analysis";
  if (!analyzed) return;

  const counts = insights.sentiment.counts;
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const sentimentList = byId("sentiment-list");
  sentimentList.replaceChildren(...["positive", "neutral", "negative"].map(label => {
    const count = counts[label] || 0;
    const percentage = total ? count / total * 100 : 0;
    const row = makeElement("div", "sentiment-row");
    const labels = makeElement("div", "sentiment-labels");
    labels.append(makeElement("span", "", label), makeElement("b", "", `${count} · ${percentage.toFixed(1)}%`));
    const track = makeElement("div", "bar-track");
    const fill = makeElement("div", `bar-fill ${label}`);
    fill.style.width = `${percentage}%`;
    track.append(fill);
    row.append(labels, track);
    return row;
  }));

  const phraseList = byId("phrase-list");
  const phrases = insights.keywords?.phrases || [];
  if (!phrases.length) {
    phraseList.replaceChildren(makeElement("p", "empty", "No repeated keywords or phrases were found in the negative reviews."));
  } else {
    phraseList.replaceChildren(...phrases.slice(0, 18).map(item => {
      const phrase = makeElement("span", "phrase");
      phrase.append(document.createTextNode(`${item.phrase} `), makeElement("strong", "", item.review_count));
      return phrase;
    }));
  }
  renderRecommendations(insights);
}

function renderRecommendations(insights) {
  const recommendations = insights.recommendations || { status: "provider_not_configured", items: [] };
  const status = byId("recommendation-status");
  const grid = byId("recommendation-grid");
  status.textContent = recommendations.status === "completed" ? "Generated with Gemini" : "Local analysis is available";
  grid.replaceChildren();
  if (!recommendations.items?.length) return;
  recommendations.items.forEach((item, index) => {
    const card = makeElement("article", "recommendation");
    card.append(makeElement("div", "recommendation-index", `PRIORITY ${String(index + 1).padStart(2, "0")}`));
    card.append(makeElement("h4", "", item.title));
    card.append(makeElement("p", "", item.observation));
    const action = makeElement("div", "action-box");
    action.append(makeElement("b", "", "Recommended action"), document.createTextNode(item.action));
    const verification = makeElement("div", "action-box");
    verification.append(makeElement("b", "", "How to verify"), document.createTextNode(item.verification));
    card.append(action, verification);
    grid.append(card);
  });
}

function filteredReviews() {
  const query = byId("review-search").value.trim().toLowerCase();
  const rating = byId("rating-filter").value;
  return state.reviews.filter(review => {
    const matchesRating = rating === "all" || String(review.rating) === rating;
    const text = `${review.title || ""} ${review.text || ""}`.toLowerCase();
    return matchesRating && (!query || text.includes(query));
  });
}

function renderReviews() {
  const reviews = filteredReviews();
  const list = byId("review-list");
  const visible = reviews.slice(0, state.visibleReviews);
  if (!visible.length) {
    list.replaceChildren(makeElement("p", "empty", "No reviews match this filter."));
  } else {
    list.replaceChildren(...visible.map(review => {
      const item = makeElement("article", "review-item");
      const top = makeElement("div", "review-top");
      top.append(makeElement("div", "review-title", review.title || "Untitled review"), makeElement("div", "stars", `${"★".repeat(review.rating)}${"☆".repeat(5 - review.rating)}`));
      item.append(top, makeElement("p", "", review.text));
      if (review.updated_at) item.append(makeElement("div", "review-date", new Date(review.updated_at).toLocaleDateString()));
      return item;
    }));
  }
  byId("show-more").classList.toggle("hidden", reviews.length <= state.visibleReviews);
}

byId("review-search").addEventListener("input", () => {
  state.visibleReviews = 10;
  renderReviews();
});

byId("rating-filter").addEventListener("change", () => {
  state.visibleReviews = 10;
  renderReviews();
});

byId("show-more").addEventListener("click", () => {
  state.visibleReviews += 10;
  renderReviews();
});

byId("analyze-button").addEventListener("click", async () => {
  if (!state.collection) return;
  setLoading(true, "Analyzing customer feedback", "Running sentiment, phrase and topic analysis. The first run may download local models.");
  try {
    state.collection = await request(`/collections/${state.collection.collection_id}/analyze`, { method: "POST" });
    renderDashboard();
    byId("insights-section").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false);
  }
});
