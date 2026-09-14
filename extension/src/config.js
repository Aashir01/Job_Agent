/**
 * Shared storage helpers.
 *
 * The agent key lives in chrome.storage.local, scoped to this extension. It is
 * the same machine key the dashboard uses, so treat the options page as a
 * credential form — nothing here is synced across browsers.
 */
export const DEFAULTS = {
  apiUrl: "",
  agentKey: "",
  harvestEnabled: true,
};

export async function getConfig() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...stored };
}

export async function setConfig(patch) {
  await chrome.storage.local.set(patch);
}

export async function api(path, init = {}) {
  const { apiUrl, agentKey } = await getConfig();
  if (!apiUrl || !agentKey) {
    throw new Error("Set the API URL and agent key in the extension options first.");
  }
  const res = await fetch(`${apiUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    headers: {
      "X-Agent-Key": agentKey,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  return res.status === 204 ? null : res.json();
}
