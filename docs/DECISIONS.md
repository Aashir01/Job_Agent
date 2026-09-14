# Why the awkward parts are the way they are

## The embeddings are a hashing trick, not a model

384 dimensions, deterministic, no weights, no network. A sentence-transformer
would be better at retrieval, but it does not fit a 256MB Fly machine and the
laptop is off the table by constraint. What embeddings are actually asked to do
here is near-duplicate detection at cosine 0.92 and top-N bullet retrieval, and
a weighted hashing trick over unigrams, bigrams and per-word character n-grams
does both.

`EMBEDDING_PROVIDER=gemini` switches to `text-embedding-004` truncated to 384
dimensions when retrieval quality matters more than the quota. The two are not
comparable — switching means re-embedding everything.

The character n-grams are taken **per word**. Striding them across the joined
text, which is the obvious implementation, means one inserted word misaligns
every feature after it: two cross-posted copies of the same job scored 0.49
instead of 0.93 and both got stored.

## PostgREST directly, not supabase-py

The official client is synchronous and brings more than a 256MB machine wants
to carry. `api/app/db.py` is about 160 lines and covers the five calls the
system makes. Vector search goes through SQL functions (`match_jobs`,
`match_bullets`) because PostgREST cannot express a `<=>` ordering.

## The daily caps live in Postgres, not in Python

`bump_daily_counter` increments and checks in one statement and returns `-1`
when the cap would be exceeded. An in-process counter would let a manual batch
and the cron batch each believe they had the full allowance, and §10's caps
exist to protect deliverability — the one thing you cannot undo.

## Traceability is a checker, not a prompt

The Tailor's system prompt does say not to invent anything. That is not why it
does not invent anything. Every rewrite is checked against its source bullet
for introduced figures and unsupported vocabulary, and a failure falls back to
the user's own words. Prompts are a request; this is a rule.

The allowed vocabulary is the source bullet plus the job description plus
function words plus a small list of restating verbs. That last list is the
judgement call: "developed" and "shipped" restate, "architected" and
"spearheaded" claim, so the second kind has to already be in the bullet.

## The Courier re-reads status from the database

It would be cheaper to trust the status on the package the route already
loaded. It does not, because that is the single line in the system where an
outbound action begins, and a gate that can be passed a stale object is not a
gate.

## `hires_internationally` is write-once

A company that has hired internationally does not stop having done so because
its next posting has boilerplate about work authorisation. The flag is only
ever set true. That asymmetry is deliberate: false negatives cost one missed
application, false positives cost a compounding asset.

## The extension fills but never submits

Partly terms of service, mostly that an autofilled application submitted
unread is worse than no application. The restriction is enforced by a test that
fails the build if `.click()` appears anywhere in the extension source, and the
service worker overwrites `autosubmit` to false regardless of what the API sent.

## The score is explainable, not learned

Five components summing to 100, then a track multiplier. A learned scorer would
be better once there are a few hundred decisions, but until then it would be
unauditable and wrong. `DecisionBias` is the compromise: past approvals and
rejections nudge the score by at most ±8, which can move a package across a
tier boundary but cannot rescue a blocked one or manufacture a fast-lane pass.

## The track multiplier is applied last

Applying it to components instead would let a strong relocation role with weak
eligibility outrank a clean remote one. §2 wants relocation to need to be
*meaningfully* stronger, and multiplying the finished score is what makes that
true: a perfect relocation package lands at 70, below a mediocre remote one.

## Uncertain eligibility never rides the fast lane

A 98-scoring package whose eligibility the Gatekeeper could not confirm is
exactly the case a human has to look at, so it is capped at `standard`
regardless of score. The fast lane is for packages where the ten-second review
is genuinely enough.

## A failed register refresh keeps the old rows

An empty `sponsor_registers` table makes `is_licensed_sponsor` return false for
everyone, which blocks every relocation role — or, read the other way, makes a
stale register look like a clean one. The refresh only deletes once the new
rows are parsed and in hand.
