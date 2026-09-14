/**
 * Passive discovery on LinkedIn and Indeed (§6, source 4).
 *
 * The user is already looking at these pages in their own logged-in session.
 * This reads what is on screen and records the URL and title — it does not
 * paginate, does not open postings, does not fetch anything, and does not run
 * when the user is not on the page. Discovery only; the server never scrapes.
 */

const SELECTORS = {
  linkedin: {
    card: "div.job-card-container, li.jobs-search-results__list-item, div.jobs-search-results-list__list-item",
    title: ".job-card-list__title, .job-card-container__link, a.job-card-list__title--link",
    company: ".job-card-container__primary-description, .artdeco-entity-lockup__subtitle",
    location: ".job-card-container__metadata-item, .artdeco-entity-lockup__caption",
  },
  indeed: {
    card: "div.job_seen_beacon, td.resultContent",
    title: "h2.jobTitle span[title], h2.jobTitle a",
    company: "[data-testid='company-name'], span.companyName",
    location: "[data-testid='text-location'], div.companyLocation",
  },
};

function source() {
  if (location.hostname.includes("linkedin.com")) return "linkedin";
  if (location.hostname.includes("indeed.com")) return "indeed";
  return null;
}

function text(root, selector) {
  const node = root.querySelector(selector);
  return (node?.getAttribute("title") || node?.textContent || "").trim().replace(/\s+/g, " ");
}

function absoluteUrl(root, kind) {
  const anchor = root.querySelector("a[href]");
  if (!anchor) return null;
  try {
    const url = new URL(anchor.getAttribute("href"), location.origin);
    // Strip the tracking query string: the canonical URL is the dedupe key.
    url.search = kind === "indeed" && url.searchParams.get("jk")
      ? `?jk=${url.searchParams.get("jk")}`
      : "";
    return url.toString();
  } catch {
    return null;
  }
}

function collect() {
  const kind = source();
  if (!kind) return [];
  const config = SELECTORS[kind];
  const out = [];
  for (const card of document.querySelectorAll(config.card)) {
    const title = text(card, config.title);
    const url = absoluteUrl(card, kind);
    if (!title || !url) continue;
    out.push({
      source: kind,
      source_url: url,
      title: title.slice(0, 300),
      company_name: text(card, config.company).slice(0, 200),
      location_raw: text(card, config.location).slice(0, 300),
    });
  }
  return out;
}

let lastCount = 0;
function sweep() {
  const sightings = collect();
  if (sightings.length && sightings.length !== lastCount) {
    lastCount = sightings.length;
    chrome.runtime.sendMessage({ type: "RECORD_SIGHTINGS", sightings });
  }
}

chrome.runtime.sendMessage({ type: "GET_CONFIG" }, (response) => {
  if (!response?.ok || !response.data?.harvestEnabled) return;
  sweep();
  // These are infinite-scroll pages; re-sweep when the list actually grows.
  const observer = new MutationObserver(() => {
    clearTimeout(observer._timer);
    observer._timer = setTimeout(sweep, 1200);
  });
  observer.observe(document.body, { childList: true, subtree: true });
});
