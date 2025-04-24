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

## License

MIT — see [LICENSE](LICENSE).
