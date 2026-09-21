/**
 * Career-page filler.
 *
 * Hard rule from §10: this script never clicks the site's Submit button. It
 * fills fields, highlights what it touched, and stops. The user reads, edits
 * and submits. There is no code path here that calls .click() on a submit
 * control, and the banner says so to the user's face.
 */

const FIELD_MAP = [
  { keys: ["first name", "firstname", "given name"], from: (p) => firstName(p.full_name) },
  { keys: ["last name", "lastname", "surname", "family name"], from: (p) => lastName(p.full_name) },
  { keys: ["full name", "your name", "name"], from: (p) => p.full_name },
  { keys: ["email", "e-mail"], from: (p) => p.email },
  { keys: ["phone", "mobile", "telephone"], from: (p) => p.phone },
  { keys: ["location", "city", "where are you based", "current location"], from: (p) => p.location },
  { keys: ["linkedin"], from: (p) => p.links?.linkedin },
  { keys: ["github"], from: (p) => p.links?.github },
  { keys: ["portfolio", "website", "personal site"], from: (p) => p.links?.portfolio },
  { keys: ["cover letter", "why do you want", "tell us about"], from: (p) => p.cover_letter },
];

function firstName(name) {
  return (name ?? "").trim().split(/\s+/)[0] ?? "";
}
function lastName(name) {
  const parts = (name ?? "").trim().split(/\s+/);
  return parts.length > 1 ? parts[parts.length - 1] : "";
}

function labelTextFor(field) {
  const bits = [
    field.getAttribute("aria-label"),
    field.getAttribute("placeholder"),
    field.getAttribute("name"),
    field.id,
  ];
  if (field.id) {
    const label = document.querySelector(`label[for="${CSS.escape(field.id)}"]`);
    if (label) bits.push(label.textContent);
  }
  bits.push(field.closest("label")?.textContent);
  bits.push(
    field.closest("div,fieldset,li")?.querySelector("label,legend,.application-label")?.textContent,
  );
  return bits.filter(Boolean).join(" ").toLowerCase().replace(/\s+/g, " ").trim();
}

function setValue(field, value) {
  // React and Vue track values on the DOM node, so assigning .value alone is
  // silently discarded on re-render. Go through the native setter.
  const prototype = field instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  setter ? setter.call(field, value) : (field.value = value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.dispatchEvent(new Event("change", { bubbles: true }));
  field.style.outline = "2px solid #3ddc97";
  field.style.outlineOffset = "1px";
}

function fillScreening(answers) {
  let filled = 0;
  for (const { question, answer } of answers ?? []) {
    if (!question || !answer) continue;
    const needle = question.toLowerCase().slice(0, 40);
    for (const field of document.querySelectorAll("textarea, input[type=text]")) {
      if (field.value.trim()) continue;
      if (labelTextFor(field).includes(needle)) {
        setValue(field, answer);
        filled += 1;
        break;
      }
    }
  }
  return filled;
}

function fill(payload) {
  let filled = 0;
  const fields = document.querySelectorAll(
    "input[type=text], input[type=email], input[type=tel], input[type=url], textarea",
  );

  for (const field of fields) {
    if (field.disabled || field.readOnly || field.value.trim()) continue;
    const label = labelTextFor(field);
    if (!label) continue;
    const match = FIELD_MAP.find((entry) => entry.keys.some((key) => label.includes(key)));
    const value = match?.from(payload);
    if (value) {
      setValue(field, value);
      filled += 1;
    }
  }

  filled += fillScreening(payload.screening_answers);
  return filled;
}

function banner(payload, filled) {
  document.getElementById("job-agent-banner")?.remove();
  const host = document.createElement("div");
  host.id = "job-agent-banner";
  host.style.cssText =
    "position:fixed;top:12px;right:12px;z-index:2147483647;max-width:340px;" +
    "font:13px/1.45 system-ui,sans-serif;color:#e6e9ef;background:#171a21;" +
    "border:1px solid #3ddc97;border-radius:10px;padding:12px 14px;" +
    "box-shadow:0 8px 28px rgba(0,0,0,.45)";

  const title = document.createElement("strong");
  title.textContent = `Filled ${filled} field${filled === 1 ? "" : "s"}`;
  title.style.cssText = "display:block;color:#3ddc97;margin-bottom:4px";

  const body = document.createElement("p");
  body.style.cssText = "margin:0 0 8px";
  body.textContent =
    "Read it, fix anything wrong, attach your resume, then click this site's own Submit button. " +
    "This extension will not submit for you.";

  const resume = document.createElement("p");
  resume.style.cssText = "margin:0 0 8px;color:#8b94a7;font-size:12px";
  resume.textContent = payload.resume_url
    ? `Resume: ${payload.resume_url}`
    : "No tailored resume was attached to this package.";

  const actions = document.createElement("div");
  actions.style.cssText = "display:flex;gap:6px";

  const done = document.createElement("button");
  done.textContent = "I submitted it";
  done.style.cssText =
    "flex:1;cursor:pointer;border:1px solid #3ddc97;background:rgba(61,220,151,.12);" +
    "color:#3ddc97;border-radius:7px;padding:5px 8px;font:inherit";
  done.addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "MARK", status: "submitted" }, () => host.remove());
  });

  const skip = document.createElement("button");
  skip.textContent = "Skip";
  skip.style.cssText =
    "cursor:pointer;border:1px solid #262b36;background:transparent;color:#8b94a7;" +
    "border-radius:7px;padding:5px 10px;font:inherit";
  skip.addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "MARK", status: "abandoned" }, () => host.remove());
  });

  actions.append(done, skip);
  host.append(title, body, resume, actions);
  document.body.appendChild(host);
}

chrome.runtime.sendMessage({ type: "GET_CURRENT" }, (response) => {
  if (!response?.ok || !response.data) return;
  const item = response.data;
  // Only act on the page this package is actually for.
  const target = new URL(item.target_url);
  if (target.hostname !== location.hostname) return;

  const filled = fill(item.payload);
  if (filled > 0) banner(item.payload, filled);
});
