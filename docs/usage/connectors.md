1|# Connector Setup Guide
2|
3|Spacetime Memory includes a **connector framework** that polls external data sources
4|and persists them as memories or knowledge-graph nodes. Each connector requires
5|API credentials from its respective platform.
6|
7|This guide covers how to obtain and configure credentials for every built-in
8|connector, then how to register and run them.
9|
10|---
11|
12|## Quick Reference
13|
14|| Connector | Credential | Where to Get It |
15||-----------|-----------|-----------------|
16|| **Discord** | Bot token (`Bot MTE...`) | [Discord Developer Portal](https://discord.com/developers/applications) |
17|| **Notion** | Integration token (`secret_...`) | [Notion Integrations](https://www.notion.so/my-integrations) |
18|| **GitHub** | Personal access token (`ghp_...`) | [GitHub Settings > Tokens](https://github.com/settings/tokens) |
19|| **Slack** | Bot token (`xoxb-...`) | [Slack API Apps](https://api.slack.com/apps) |
| **Telegram** | Bot token (`123456:ABC-DEF1234...`) | [BotFather](https://t.me/BotFather) on Telegram |
20|| **Twitter/X** | Bearer token (`AAAA...`) | [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard) |
21|| **RSS** | *(none — feed URL only)* | Any RSS/Atom feed URL |
22|| **Webhook** | *(optional)* HMAC secret | You define it |
23|| **Org-mode** | *(none — file path only)* | Local `.org` file |
24|
25|---
26|
27|## 1. Discord Bot Token
28|
29|The Discord connector polls messages from one or more channels using the
30|Discord REST API. It requires a **Bot token**.
31|
32|### Step-by-Step
33|
34|1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
35|   and click **New Application**. Give it a name (e.g. "Spacetime Memory Bridge").
36|2. In the left sidebar, go to **Bot** → **Add Bot** → confirm.
37|3. Under the **Token** section, click **Reset Token** then **Copy**.
38|   - The token looks like: `MTE2NzEwNjQ4NTQ3OTM4NTYwMg.GbBcX.abc123...`
39|   - **Keep this secret.** Never commit it to version control.
40|4. Scroll down to **Privileged Gateway Intents** and enable:
41|   - **Message Content Intent** (required to read message text)
42|5. In the left sidebar, go to **OAuth2** → **URL Generator**:
43|   - Scopes: `bot`
44|   - Bot Permissions: `Read Messages`, `Read Message History`, `View Channels`
45|   - Open the generated URL in your browser to invite the bot to your server.
46|6. Find a channel ID you want to poll:
47|   - Enable **Developer Mode** in Discord (Settings → Advanced → Developer Mode).
48|   - Right-click a channel → **Copy Channel ID**.
49|
50|### Testing
51|
52|```python
53|from spacetime_memory.connectors import DiscordConnector
54|
55|c = DiscordConnector(
56|    token="MTE...",             # your bot token
57|    channel_ids=["123", "456"], # channel IDs to poll
58|    workspace_id="ws-1",
59|)
60|events = c.poll()
61|print(f"Found {len(events)} new messages")
62|```
63|
64|---
65|
66|## 2. Notion Integration Token
67|
68|The Notion connector polls a Notion database for new or updated pages using
69|the Notion API. It requires an **Integration token**.
70|
71|### Step-by-Step
72|
73|1. Go to [Notion Integrations](https://www.notion.so/my-integrations) and
74|   click **New Integration**.
75|2. Give it a name (e.g. "Spacetime Memory") and select the workspace.
76|   - **Capabilities**: at minimum, `Read content`.
77|3. Click **Submit**, then copy the **Internal Integration Secret**.
78|   - The token starts with `secret_`: `secret_abc123DEF456...`
79|4. Share the integration with your database:
80|   - Open your Notion database in the browser.
81|   - Click **Share** in the top-right corner.
82|   - Under **Invite**, add your integration by name.
83|5. Copy the **Database ID** from the URL:
84|   - `https://www.notion.so/workspace/ABC123def456...?v=...`
85|   - The part between the last `/` and `?` is the database ID.
86|
87|### Testing
88|
89|```python
90|from spacetime_memory.connectors import NotionConnector
91|
92|c = NotionConnector(
93|    token="secret_...",     # integration token
94|    database_id="abc123",   # database UUID
95|    workspace_id="ws-1",
96|)
97|events = c.poll()
98|print(f"Found {len(events)} new pages")
99|```
100|
101|---
102|
103|## 3. GitHub Personal Access Token
104|
105|The GitHub connector polls a user's public events. It requires a
106|**Personal Access Token (classic or fine-grained)**.
107|
108|### Step-by-Step
109|
110|1. Go to [GitHub Settings > Tokens](https://github.com/settings/tokens).
111|2. Click **Generate new token (classic)**.
112|3. Give it a name (e.g. "spacetime-memory").
113|4. Select scopes:
114|   - **Minimal**: no scopes needed for public events.
115|   - **Private repos**: you need `repo` scope.
116|5. Click **Generate token** and copy it immediately.
117|   - Classic tokens start with `ghp_`: `ghp_abc123DEF456...`
118|   - Fine-grained tokens start with `github_pat_...`
119|6. Find your GitHub username (the `@username` from your profile URL).
120|
121|### Testing
122|
123|```python
124|from spacetime_memory.connectors import GitHubConnector
125|
126|c = GitHubConnector(
127|    token="ghp_...",        # personal access token
128|    username="octocat",     # GitHub username
129|    workspace_id="ws-1",
130|)
131|events = c.poll()
132|print(f"Found {len(events)} new events")
133|```
134|
135|---
136|
137|## 4. Slack Bot Token
138|
139|The Slack connector polls one or more channels using the Slack Web API.
140|It requires a **Bot Token** (`xoxb-...`).
141|
142|### Step-by-Step
143|
144|1. Go to [Slack API Apps](https://api.slack.com/apps) and click **Create New App**.
145|   - Choose **From an app manifest** if you want a quick start, or
146|     **From scratch** for custom setup.
147|2. In **OAuth & Permissions**, add these **Bot Token Scopes**:
148|   - `channels:history` — read message history in public channels
149|   - `channels:read` — view channel names and metadata
150|   - `groups:history` — read message history in private channels (optional)
151|   - `groups:read` — view private channel metadata (optional)
152|   - `users:read` — resolve user IDs to names (optional)
153|3. Install the app to your workspace via **Install to Workspace**.
154|4. Copy the **Bot User OAuth Token**.
155|   - The token starts with `xoxb-`: `xoxb-1234567890-abc123...`
156|5. Find channel IDs:
157|   - Open Slack, right-click a channel → **Copy link**.
158|   - The channel ID is the `C...` part (e.g. `C0123ABC456`).
159|
160|### Testing
161|
162|```python
163|from spacetime_memory.connectors import SlackConnector
164|
165|c = SlackConnector(
166|    token="xoxb-...",           # bot token
167|    channel_ids=["C123", "C456"], # channel IDs
168|    workspace_id="ws-1",
169|)
170|events = c.poll()
171|print(f"Found {len(events)} new messages")
172|```
173|
174|---
175|
176|---

## 5. Telegram Bot Token

This guide covers how to obtain and configure credentials for every built-in
connector, then how to register and run them.

---

## Quick Reference

| Connector | Credential | Where to Get It |
|-----------|-----------|-----------------|
| **Discord** | Bot token (`Bot MTE...`) | [Discord Developer Portal](https://discord.com/developers/applications) |
| **Notion** | Integration token (`secret_...`) | [Notion Integrations](https://www.notion.so/my-integrations) |
| **GitHub** | Personal access token (`ghp_...`) | [GitHub Settings > Tokens](https://github.com/settings/tokens) |
| **Slack** | Bot token (`xoxb-...`) | [Slack API Apps](https://api.slack.com/apps) |
| **Telegram** | Bot token (`123456:ABC-DEF1234...`) | [BotFather](https://t.me/BotFather) on Telegram |
| **Twitter/X** | Bearer token (`AAAA...`) | [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard) |
| **RSS** | *(none — feed URL only)* | Any RSS/Atom feed URL |
| **Webhook** | *(optional)* HMAC secret | You define it |
| **Org-mode** | *(none — file path only)* | Local `.org` file |

---

## 1. Discord Bot Token

The Discord connector polls messages from one or more channels using the
Discord REST API. It requires a **Bot token**.

### Step-by-Step

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts:
   - Choose a display name (e.g. "Spacetime Memory Bridge").
   - Choose a username ending in `bot` (e.g. `spacetime_memory_bot`).
3. BotFather replies with the **HTTP API token**:
   - The token looks like: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
   - **Keep this secret.** Never commit it to version control.
4. (Optional) Configure privacy settings:
   - Send `/setprivacy` to BotFather, select your bot, and choose **Disabled**
     to let the bot see all messages in groups it's added to (not just commands).
5. Find chat IDs:
   - **Group chat**: Add the bot to a group. Send a message, then visit:
     `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - The response includes `"chat":{"id":-1001234567890,...}` — this is the
     chat ID (negative for groups/supergroups).
   - For a single-user bot conversation, send `/start` to the bot and check
     the same endpoint.
6. Add the bot to any channel/group you want to monitor:
   - Open the group/channel → **Add Members** → search for your bot's username.

### Testing

```python
from spacetime_memory.connectors import TelegramConnector

c = TelegramConnector(
    token="123456:ABC-DEF1234...",         # bot token
    chat_ids=["-1001234567890"],            # optional — poll all chats if empty
    workspace_id="ws-1",
)
events = c.poll()
print(f"Found {len(events)} new messages")
```

### Polling Modes

- **Specific chats**: Pass `chat_ids=["-1001234567890", "12345"]` to poll only
  those chats. Message updates from other chats are dropped.
- **All chats**: Omit `chat_ids` or pass an empty list — the connector polls
  every chat the bot has access to.
- **Include callback queries**: Set `include_callback_queries=False` to skip
  inline keyboard button presses (default: `True`).

---

## 3. GitHub Personal Access Token

The GitHub connector polls a user's public events. It requires a
**Personal Access Token (classic or fine-grained)**.

### Step-by-Step

1. Go to [GitHub Settings > Tokens](https://github.com/settings/tokens).
2. Click **Generate new token (classic)**.
3. Give it a name (e.g. "spacetime-memory").
4. Select scopes:
   - **Minimal**: no scopes needed for public events.
   - **Private repos**: you need `repo` scope.
5. Click **Generate token** and copy it immediately.
   - Classic tokens start with `ghp_`: `ghp_abc123DEF456...`
   - Fine-grained tokens start with `github_pat_...`
6. Find your GitHub username (the `@username` from your profile URL).

### Testing

```python
from spacetime_memory.connectors import GitHubConnector

c = GitHubConnector(
    token="ghp_...",        # personal access token
    username="octocat",     # GitHub username
    workspace_id="ws-1",
)
events = c.poll()
print(f"Found {len(events)} new events")
```

---

## 4. Slack Bot Token

The Slack connector polls one or more channels using the Slack Web API.
It requires a **Bot Token** (`xoxb-...`).

### Step-by-Step

1. Go to [Slack API Apps](https://api.slack.com/apps) and click **Create New App**.
   - Choose **From an app manifest** if you want a quick start, or
     **From scratch** for custom setup.
2. In **OAuth & Permissions**, add these **Bot Token Scopes**:
   - `channels:history` — read message history in public channels
   - `channels:read` — view channel names and metadata
   - `groups:history` — read message history in private channels (optional)
   - `groups:read` — view private channel metadata (optional)
   - `users:read` — resolve user IDs to names (optional)
3. Install the app to your workspace via **Install to Workspace**.
4. Copy the **Bot User OAuth Token**.
   - The token starts with `xoxb-`: `xoxb-1234567890-abc123...`
5. Find channel IDs:
   - Open Slack, right-click a channel → **Copy link**.
   - The channel ID is the `C...` part (e.g. `C0123ABC456`).

### Testing

```python
from spacetime_memory.connectors import SlackConnector

c = SlackConnector(
    token="xoxb-...",           # bot token
    channel_ids=["C123", "C456"], # channel IDs
    workspace_id="ws-1",
)
events = c.poll()
print(f"Found {len(events)} new messages")
```

---

---

## 5. Telegram Bot Token

The Telegram connector polls a bot for new messages from one or more chats
using the Telegram Bot API. It requires a **Bot token** obtained from
[BotFather](https://t.me/BotFather).

### Step-by-Step

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts:
   - Choose a display name (e.g. "Spacetime Memory Bridge").
   - Choose a username ending in `bot` (e.g. `spacetime_memory_bot`).
3. BotFather replies with the **HTTP API token**:
   - The token looks like: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
   - **Keep this secret.** Never commit it to version control.
4. (Optional) Configure privacy settings:
   - Send `/setprivacy` to BotFather, select your bot, and choose **Disabled**
     to let the bot see all messages in groups it's added to (not just commands).
5. Find chat IDs:
   - **Group chat**: Add the bot to a group. Send a message, then visit:
     `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - The response includes `"chat":{"id":-1001234567890,...}` -- this is the
     chat ID (negative for groups/supergroups).
   - For a single-user bot conversation, send `/start` to the bot and check
     the same endpoint.
6. Add the bot to any channel/group you want to monitor:
   - Open the group/channel -> **Add Members** -> search for your bot's username.

### Testing

```python
from spacetime_memory.connectors import TelegramConnector

c = TelegramConnector(
    token="123456:ABC-DEF1234...",         # bot token
    chat_ids=["-1001234567890"],            # optional -- poll all chats if empty
    workspace_id="ws-1",
)
events = c.poll()
print(f"Found {len(events)} new messages")
```

### Polling Modes

- **Specific chats**: Pass `chat_ids=["-1001234567890", "12345"]` to poll only
  those chats. Message updates from other chats are dropped.
- **All chats**: Omit `chat_ids` or pass an empty list -- the connector polls
  every chat the bot has access to.
- **Include callback queries**: Set `include_callback_queries=False` to skip
  inline keyboard button presses (default: `True`).

---

## 6. Twitter/X Bearer Token

The Twitter/X connector polls tweets from a user or list using the
Twitter API v2. It requires a **Bearer Token**.

### Step-by-Step

1. Go to the [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard).
   - If you don't have a project, create one (requires a Project name).
2. Go to **Projects & Apps** → your project → **Keys and Tokens**.
3. Scroll to **Bearer Token** and click **Regenerate** then **Copy**.
   - The token is a long base64 string: `AAAA...`
4. Find the user or list ID:
   - **User ID**: use [Pastebin's ID converter](https://www.pastebin.com/u/yourusername)
     or the `users/:username` API endpoint.
   - **List ID**: open your Twitter list in a browser and copy the numeric
     ID from the URL.

### Testing

```python
from spacetime_memory.connectors import TwitterConnector

# By user ID
c = TwitterConnector(
    bearer_token="AAAA...",  # API v2 bearer token
    user_id="123456789",     # target user ID
    workspace_id="ws-1",
)

# Or by list ID
c = TwitterConnector(
    bearer_token="AAAA...",
    list_id="123456789",
    workspace_id="ws-1",
)

events = c.poll()
print(f"Found {len(events)} new tweets")
```

---

## 7. RSS Feed

The RSS connector polls an RSS or Atom feed URL. No API credentials are needed,
just a public feed URL.

### Usage

```python
from spacetime_memory.connectors import RssFeedConnector

c = RssFeedConnector(
    feed_url="https://example.com/blog/feed.xml",
    workspace_id="ws-1",
)
events = c.poll()
for ev in events:
    print(ev.summary)
```

---

## 8. Webhook

The Webhook connector receives events via HTTP POST. It does **not** poll.
You pass the payload to `handle()` from your HTTP handler.

### Usage

```python
from spacetime_memory.connectors import WebhookConnector

c = WebhookConnector(
    path="/webhook",          # route or identifier
    workspace_id="ws-1",
    secret="my-hmac-secret",  # optional — enables HMAC verification
)

# In your HTTP handler:
# events = c.handle(request.json(), dict(request.headers))
```

---

## 9. Org-mode Parser

The Org-mode parser reads an Emacs org-mode file and converts headings into
memory events. No credentials needed — works with local files.

### Usage

```python
from spacetime_memory.connectors import OrgModeParser

parser = OrgModeParser(
    file_path="/path/to/notes.org",
    workspace_id="ws-1",
)
events = parser.parse()
```

---

## Using Connectors

### Method A: Programmatic (Python)

Each connector is a regular Python class. Instantiate it, call `poll()`, then
store results with a `Client`:

```python
from spacetime_memory import Client
from spacetime_memory.connectors import DiscordConnector

client = Client()
connector = DiscordConnector(
    token="MTE...",
    channel_ids=["123"],
    workspace_id="ws-1",
)

events = connector.poll()
for ev in events:
    client.store(
        workspace_id=ev.workspace_id,
        content=ev.content,
        summary=ev.summary,
        memory_type=ev.memory_type,
        peer_id=ev.peer_id,
    )
```

For continuous polling, use `connector.run(client, interval_secs=60)`.

### Method B: CLI

```bash
# List registered connectors
stmem connector list

# Register a connector in the database
stmem connector register discord \
    --type discord \
    --config '{"token": "MTE...", "channel_ids": ["123"]}' \
    --workspace ws-1 \
    --interval 300

# Run one-off
stmem connector run --rss https://example.com/feed.xml --workspace ws-1
```

### Method C: Connector Daemon

The `ConnectorDaemon` loads connector configs from the database and runs them
in a continuous poll loop:

```python
from spacetime_memory import Client
from spacetime_memory.connectors import ConnectorDaemon

client = Client()
daemon = ConnectorDaemon(client)
daemon.start()  # blocks until Ctrl+C
```

---

## Environment Variable Reference

Comprehensive environment config docs are in [CONFIG.md](../CONFIG.md).
The connector system specifically reads:

| Variable | Default | Used By |
|----------|---------|---------|
| `SPACETIMEDB_HOST` | `localhost` | All connectors (via Client) |
| `SPACETIMEDB_PORT` | `3001` | All connectors (via Client) |
| `SPACETIMEDB_DB` | `spacetime-memory` | All connectors (via Client) |
| `MCP_API_KEY` | *(none)* | MCP server auth (HTTP/SSE only) |

Individual connector tokens are **not** read from environment variables —
they are passed as constructor arguments or stored in the connector config
in the database. For production, use a secrets manager or inject them via
your deployment pipeline.

---

## Security Notes

- **Never commit tokens to version control.** Use `.env` files, a secrets
  manager, or environment variables in production.
- The `.env` file is in `.gitignore`. Copy `.env.example` to `.env` for
  local development:
  ```bash
  cp .env.example .env
  ```
- Connector configs stored in the database (`connector_config` table) are
  **not encrypted at rest**. If your SpacetimeDB instance is accessible
  over the network, restrict access with JWT authentication and firewall
  rules.
- For the Webhook connector, always set a `secret` in production to enable
  HMAC payload verification.



