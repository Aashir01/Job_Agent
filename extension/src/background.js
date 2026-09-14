import { api, getConfig } from "./config.js";

/**
 * The service worker holds the currently claimed fill job and answers the
 * content script when it asks what to type. It never navigates, never clicks,
 * and never opens a tab on its own — the user drives.
 */

const HARVEST_BUFFER_KEY = "harvestBuffer";
const FLUSH_ALARM = "flush-sightings";

chrome.runtime.onInstalled.addListener(() => {
  // Batch passive sightings rather than posting one request per scroll.
  chrome.alarms.create(FLUSH_ALARM, { periodInMinutes: 5 });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === FLUSH_ALARM) void flushSightings();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handle(message)
    .then((data) => sendResponse({ ok: true, data }))
    .catch((error) => sendResponse({ ok: false, error: String(error.message ?? error) }));
  return true; // keep the channel open for the async reply
});

async function handle(message) {
  switch (message.type) {
    case "CLAIM_NEXT":
      return claimNext();
    case "GET_CURRENT":
      return (await chrome.storage.local.get("current")).current ?? null;
    case "MARK":
      return mark(message.status, message.note);
    case "RECORD_SIGHTINGS":
      return bufferSightings(message.sightings);
    case "FLUSH_SIGHTINGS":
      return flushSightings();
    case "GET_CONFIG":
      return getConfig();
    default:
      throw new Error(`unknown message ${message.type}`);
  }
}

async function claimNext() {
  const { item } = await api("/extension/queue/next");
  if (!item) {
    await chrome.storage.local.remove("current");
    await chrome.action.setBadgeText({ text: "" });
    return null;
  }
  // Defence in depth: the API already forces this false, and we force it again
  // here so no payload shape can ever talk the content script into submitting.
  item.payload.autosubmit = false;
  await chrome.storage.local.set({ current: item });
  await chrome.action.setBadgeText({ text: "1" });
  await chrome.action.setBadgeBackgroundColor({ color: "#3ddc97" });
  return item;
}

async function mark(status, note) {
  const { current } = await chrome.storage.local.get("current");
  if (!current) throw new Error("nothing claimed");
  await api(`/extension/queue/${current.id}/status`, {
    method: "POST",
    body: JSON.stringify({ status, note: note ?? null }),
  });
  await chrome.storage.local.remove("current");
  await chrome.action.setBadgeText({ text: "" });
  return { status };
}

async function bufferSightings(sightings) {
  if (!Array.isArray(sightings) || !sightings.length) return { buffered: 0 };
  const { harvestEnabled } = await getConfig();
  if (!harvestEnabled) return { buffered: 0 };

  const store = await chrome.storage.local.get(HARVEST_BUFFER_KEY);
  const buffer = store[HARVEST_BUFFER_KEY] ?? [];
  const seen = new Set(buffer.map((s) => s.source_url));
  for (const sighting of sightings) {
    if (sighting?.source_url && !seen.has(sighting.source_url)) {
      buffer.push(sighting);
      seen.add(sighting.source_url);
    }
  }
  await chrome.storage.local.set({ [HARVEST_BUFFER_KEY]: buffer.slice(-200) });
  if (buffer.length >= 25) await flushSightings();
  return { buffered: buffer.length };
}

async function flushSightings() {
  const store = await chrome.storage.local.get(HARVEST_BUFFER_KEY);
  const buffer = store[HARVEST_BUFFER_KEY] ?? [];
  if (!buffer.length) return { sent: 0 };
  try {
    // The API caps a batch at 50.
    const chunk = buffer.slice(0, 50);
    await api("/extension/sightings", {
      method: "POST",
      body: JSON.stringify({ sightings: chunk }),
    });
    await chrome.storage.local.set({ [HARVEST_BUFFER_KEY]: buffer.slice(chunk.length) });
    return { sent: chunk.length };
  } catch (error) {
    // Keep the buffer: a failed flush is retried on the next alarm.
    console.warn("job-agent: sighting flush failed", error);
    return { sent: 0, error: String(error.message ?? error) };
  }
}
