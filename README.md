# email-agent

A local email monitoring agent. It watches a Gmail inbox, asks a local model
(Ollama) how urgent each new email is, and logs an alert when something needs
attention. Nothing leaves the machine except the model calls you choose to
make.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
ollama pull llama3.1:8b
```

Create a Gmail OAuth client (Desktop app) in Google Cloud Console, download
the JSON to `~/.email-agent/credentials.json`, then:

```bash
email-agent auth     # opens a browser once, read-only scope
email-agent run      # polls every minute, logs alerts
```

Settings live in `~/.email-agent/email_agent.db`. Tests run offline:

```bash
pip install -e ".[dev]" && pytest
```

MIT licensed.
