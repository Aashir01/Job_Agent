import { DEFAULTS, getConfig, setConfig } from "./config.js";

const fields = {
  apiUrl: document.getElementById("apiUrl"),
  agentKey: document.getElementById("agentKey"),
  harvestEnabled: document.getElementById("harvestEnabled"),
};
const status = document.getElementById("status");

const config = await getConfig();
fields.apiUrl.value = config.apiUrl;
fields.agentKey.value = config.agentKey;
fields.harvestEnabled.checked = config.harvestEnabled;

document.getElementById("save").addEventListener("click", async () => {
  await setConfig({
    apiUrl: fields.apiUrl.value.trim(),
    agentKey: fields.agentKey.value.trim(),
    harvestEnabled: fields.harvestEnabled.checked,
  });
  status.textContent = "Saved";
  setTimeout(() => (status.textContent = ""), 1600);
});

void DEFAULTS;
