# email-agent

A local email monitoring agent. It watches your Gmail or Outlook inbox, decides what
actually needs your attention, and shows you why — on a small web UI that
runs on your own machine. Nothing leaves your computer except the model calls
you choose to make (local Ollama by default).

It is tuned for two people in particular:

- **Students** — assignment and exam deadlines, professor emails, registration
  and financial-aid windows, class changes. Campus newsletters and vendor
  promotions stay quiet even when they shout "urgent".
- **On-call engineers** — production incidents, pages and escalations, failed
  deploys, security advisories. Resolved incidents rank below open ones;
  staging ranks below production.

Pick a profile in Settings and the agent reads every email with that context.

## Quick start

The shortest path from clone to a running inbox. You need Python 3.11+,
[Ollama](https://ollama.com) installed, and one mailbox to watch.

**1. Install the agent**

```bash
git clone https://github.com/jycd25/email-agent.git
cd email-agent
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

**2. Get a model**

```bash
ollama pull llama3.1:8b            # the default; any chat model works
```

Ollama must be running in the background (`ollama serve`, or the desktop app).
Prefer OpenAI instead? Put `OPENAI_API_KEY=...` in a `.env` file and switch
the provider in Settings later. No key is needed for Ollama.

**3. Sign in to your mailbox** (one of the two is enough)

*Gmail:* in [Google Cloud Console](https://console.cloud.google.com) create a
project, enable the Gmail API, and create an OAuth client of type
**Desktop app**. Download its JSON and save it as
`~/.email-agent/credentials.json`. Then:

```bash
email-agent auth gmail             # opens a browser once, read-only scope
```

*Outlook / Microsoft 365* (most school and work mailboxes): register an app in
[Microsoft Entra](https://entra.microsoft.com) with **Allow public client
flows** enabled and the `Mail.Read` delegated permission. Put its Application
(client) ID in `.env` as `EMAIL_AGENT_OUTLOOK_CLIENT_ID`. Then:

```bash
email-agent auth outlook           # prints a device code; sign in at the URL shown
```

Authorize both if you like. Every signed-in account is polled into the same inbox.

**4. Start it**

```bash
email-agent ui                     # opens http://127.0.0.1:8000
```

The browser opens on the inbox. Go to **Settings**, pick the *Student* or
*On-call* profile, and leave the tab open. New mail is fetched, analyzed and
ranked as it arrives; anything above your alert threshold shows in the alert
feed and as a desktop notification.

That is the whole setup. Everything below is detail.

## What it does

Every new email goes through up to three checks, each producing a result you
can inspect and an alert if it crosses your threshold:

| Check     | Question it answers                              | Cost                      |
|-----------|--------------------------------------------------|---------------------------|
| Urgency   | How soon do I need to act, and on what?          | 1 model call, 2 if it matters |
| Watchlist | Is this about one of the topics I care about?    | 1 model call, 2 if it matters |
| Sender    | Who is this from — trusted, blocked, VIP, noise? | 0 calls if a rule matches |

Blocked senders stop the pipeline early. Quick checks that come back
confident and boring stop early too, so most mail costs one cheap call.

The UI shows the inbox with a severity rail, per-email analysis, an alert
feed, an ad-hoc analyzer, and settings. It updates live as mail arrives.

## Command line

```bash
email-agent ui                     # web UI + background worker
email-agent run                    # worker only, no UI
email-agent fetch                  # check once and exit
email-agent status                 # queue and connection state as JSON
email-agent auth gmail|outlook     # sign in to a mailbox
email-agent analyze "is this urgent: {Prod API error rate at 12%, checkouts failing}"
email-agent analyze "analyze sender prof@university.edu"
email-agent analyze --file saved-message.eml      # or:  cat msg.eml | email-agent analyze -f -
```

Plain-English instructions work in Settings or via the API:

```
monitor urgency, starting now
monitor topic Security Incident, starting today 9am
track sender advisor@university.edu, from yesterday
```

## Configuration

Static settings come from the environment (see [.env.example](.env.example)).
Everything else — profile, model, thresholds, watchlist, sender rules, poll
interval — is edited in the UI and stored in `~/.email-agent/email_agent.db`.

Sender rules are exact addresses, `*@domain`, or `/regex/`. Rules run before
the model, so a rule for your professor's or your pager's domain makes those
emails free to classify.

Alerts at or above a level you choose also raise a desktop notification
(macOS, Linux with `notify-send`, Windows). Analyzed mail is deleted after
90 days by default; set retention to 0 to keep everything.

An optional local SMTP listener (Settings → Checking mail) lets other tools
push email straight in: `swaks --to x --server 127.0.0.1:8025 < msg.eml`.

## How it is built

```
src/email_agent/
  core/        config, events, logging
  store/       SQLite (WAL): emails, analyses, alerts, rules, settings
  sources/     Gmail API, Microsoft Graph, local SMTP, RFC 822 parsing
  llm/         one client for Ollama and OpenAI, structured output
  analyzers/   urgency, topic, sender, classifier + all prompts in prompts.py
  pipeline/    the single worker loop: fetch → claim → analyze → alert
  api/         FastAPI on localhost, SSE for live updates, serves the UI
  web/dist/    built React app (shipped in the wheel)
frontend/      React + TypeScript source (Vite)
tests/         pytest, offline — Gmail, Outlook and the model are faked
```

The reasoning behind the main choices, for whoever touches the code next:

**One queue, one loop.** Mail enters through `sources/` and is written to the
`emails` table with `status = queued`. A single worker (`pipeline/worker.py`)
claims batches with an atomic `UPDATE ... WHERE status='queued'`, runs the
analyzers, stores results, and marks `done` or `failed`. There is no second
queue, no per-email files, no directory scanning. Failures are retried on the
*next* poll, not immediately, so a flapping model does not burn every attempt
in one tick. Anything still `processing` at startup was interrupted and goes
back to `queued`.

**The loop never dies quietly.** Any exception inside a tick is logged, turned
into a system alert, and the loop continues. Fetch failures of any kind (auth
refresh, network, quota) are reported the same way. A "check now" that arrives
mid-tick is honored on the next iteration rather than dropped.

**Sources are polled if signed in, not if selected.** There is no "which
provider" setting. Each source exposes `is_authorized()`, and the worker polls
every source that says yes, so a personal Gmail and a school Outlook land in
one inbox without choosing. Outlook uses MSAL's device-code flow because
school tenants often break local redirect servers, and because it works over
SSH. Both token files are written with mode `0600`.

**Fetches are batched.** Message ids come from one `list` call; bodies come
from one batch HTTP request (Gmail's batch endpoint, Graph's `/$batch` in
chunks of 20) instead of one round trip per message. Already-seen ids are
filtered first, so a poll that finds nothing new costs a single request.

**Two-stage checks.** Urgency and topic analysis first run a cheap check
(level + confidence). If the result is confidently below the threshold, that
is the answer. Only possible hits get the full pass with summaries, deadlines
and keywords. Bodies are clipped to a few thousand characters (head plus a
little tail) before they reach the model; local models slow down sharply on
long inputs and the signal is almost always near the top.

**Analyzers are pure.** Each analyzer takes a model client and returns a
pydantic result. They do not read settings, write to the store, or raise
alerts. The worker owns the thresholds and decides what becomes an alert,
which keeps the analyzers testable with a fake model and keeps the "when do we
alert" policy in one place.

**Prompts carry the persona.** `analyzers/prompts.py` holds every prompt. Each
opens with a persona block chosen by the `profile` setting (general / student /
on-call), then the task rubric. The persona says what the user cares about
and, just as importantly, what to ignore — campus digests, vendor marketing,
"all green" reports. Tuning a profile is a one-file change.

**Single model client.** Ollama exposes an OpenAI-compatible endpoint, so one
`LLMClient` covers both providers. Structured output uses
`beta.chat.completions.parse` with a pydantic schema and falls back to
`json_object` mode plus manual validation when a provider lacks JSON schema.

**SQLite, not JSON files.** Everything the app remembers lives in one SQLite
file in WAL mode: emails and their raw bytes, analysis results, alerts, sender
rules, runtime settings. Writes are short transactions; readers never block.
Each thread keeps one connection open and reuses it.

**Retention counts from finish time.** Old mail is pruned by `updated_at`
(when processing finished), not by the email's own date. Otherwise pointing
`fetch_since` at a months-old backlog would delete everything the moment it
was analyzed.

**Local by design.** The API binds to `127.0.0.1`. The UI is static files
served by the same process and uses system fonts so it works offline. There
is no auth layer because there is no remote access.

**Tests run offline.** `tests/conftest.py` provides `FakeLLM`, which returns
canned pydantic objects per schema and records every call. Pipeline tests use
a `FakeSource`. API tests run the FastAPI app in-process with httpx. Nothing
touches Gmail, Outlook, or a real model.

## Develop

```bash
pip install -e ".[dev]"
pytest                             # ~60 tests, no network
ruff check src tests && ruff format --check src tests

cd frontend && npm install
npm run dev                        # Vite on :5173, proxies /api to :8000
npm run build                      # writes src/email_agent/web/dist
```

`python -m build` produces a wheel that includes the built UI.

## License

MIT — see [LICENSE](LICENSE).
