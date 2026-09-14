const body = document.getElementById("body");

document.getElementById("options").addEventListener("click", (event) => {
  event.preventDefault();
  chrome.runtime.openOptionsPage();
});

function send(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

function render(html) {
  body.replaceChildren();
  body.insertAdjacentHTML("beforeend", html);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

async function refresh() {
  const current = await send({ type: "GET_CURRENT" });
  if (current?.ok && current.data) {
    const item = current.data;
    render(`
      <div class="card">
        <strong>${escapeHtml(item.payload.job_title ?? "Application")}</strong>
        <p class="muted" style="margin:4px 0 0">${escapeHtml(item.target_url)}</p>
      </div>
      <button class="primary" id="open">Open the posting</button>
      <button id="skip">Skip this one</button>
    `);
    document.getElementById("open").addEventListener("click", () => {
      chrome.tabs.create({ url: item.target_url });
    });
    document.getElementById("skip").addEventListener("click", async () => {
      await send({ type: "MARK", status: "abandoned" });
      void refresh();
    });
    return;
  }

  render(`
    <p class="muted">Nothing claimed.</p>
    <button class="primary" id="claim">Claim the next approved application</button>
    <button id="flush">Send harvested postings now</button>
  `);

  document.getElementById("claim").addEventListener("click", async () => {
    const result = await send({ type: "CLAIM_NEXT" });
    if (!result?.ok) {
      body.insertAdjacentHTML("beforeend", `<p class="err">${escapeHtml(result?.error)}</p>`);
      return;
    }
    if (!result.data) {
      body.insertAdjacentHTML("beforeend", `<p class="muted">Queue is empty.</p>`);
      return;
    }
    void refresh();
  });

  document.getElementById("flush").addEventListener("click", async () => {
    const result = await send({ type: "FLUSH_SIGHTINGS" });
    const sent = result?.data?.sent ?? 0;
    body.insertAdjacentHTML(
      "beforeend",
      `<p class="muted">Sent ${escapeHtml(sent)} sightings.</p>`,
    );
  });
}

void refresh();
