# Spacetime Memory Clipper - Chrome Extension

Clip web pages, selections, and screenshots directly into your [Spacetime Memory](https://github.com/spacetime-memory) workspace.

## Features

- **Page Clipping** — Clip the current page with one click
- **Selection Clipping** — Highlight text and clip just your selection
- **Context Menu** — Right-click any page or selection to clip it
- **Keyboard Shortcut** — `Ctrl+Shift+S` to clip instantly (configurable at `chrome://extensions/shortcuts`)
- **Clip Counter** — Badge shows how many clips you've made this session
- **Clip History** — Last 5 clips shown in the popup
- **Toast Notifications** — Success/error feedback without intrusive alerts
- **Configurable** — Set your SpacetimeDB host, database identity, workspace ID, and peer ID

## Installation

1. Open Chrome/Edge/Brave and go to `chrome://extensions`
2. Enable **Developer mode** (toggle in top-right corner)
3. Click **Load unpacked**
4. Select this directory: `spacetime-memory/extensions/chrome/`
5. The extension appears in your toolbar — pin it for easy access

## Configuration

Before clipping, open the extension popup and expand **Settings**. Fill in:

| Setting | Description | Default |
|---------|-------------|---------|
| **SpacetimeDB Host** | Hostname:port of your SpacetimeDB instance | `localhost:3001` |
| **Database Identity** | The database identity to write to | *(required)* |
| **Workspace ID** | Your workspace identifier | *(required)* |
| **Peer ID** | Identifier for this browser/extension | `browser-extension` |

These are saved to `chrome.storage.local` and persist across browser sessions.

## Usage

### Via Popup
1. Click the extension icon in the toolbar
2. Verify the page info looks correct
3. Click **Clip Page to Memory** — or select text first to clip selection

### Via Context Menu
- Right-click anywhere on a page → **Clip Page to Spacetime Memory**
- Select text → right-click → **Clip Selection to Spacetime Memory**

### Via Keyboard Shortcut
- Press `Ctrl+Shift+S` (default) to clip the current page
- Customize at `chrome://extensions/shortcuts`

## Architecture

```
chrome/
├── manifest.json        # Extension manifest (Manifest V3)
├── background.js        # Service worker — handles menus, API calls, state
├── content.js           # Content script — captures page data and selections
├── popup.html           # Popup UI
├── popup.js             # Popup logic
├── styles.css           # Dark-themed shadcn-style UI
├── icons/
│   ├── icon16.png
│   ├── icon48.png
│   └── icon128.png
└── README.md
```

## API

The extension calls `store_memory` on your SpacetimeDB instance:

```
POST http://{host}/v1/database/{dbIdentity}/call/store_memory
```

Payload:
```json
[
  "<workspaceId>",
  "<peerId>",
  "",
  "experience",
  "<page content or URL>",
  "<page title>",
  "[]",
  0.8,
  "",
  ""
]
```

## Development

To modify the extension:

1. Edit the source files
2. Go to `chrome://extensions`
3. Click the refresh icon on the extension card
4. Test the changes

For background.js changes, also refresh the service worker from the extension's detail view.

## Troubleshooting

- **"Missing configuration"** — Open the popup, expand Settings, and fill in the required fields
- **CORS errors** — Ensure your SpacetimeDB instance allows `localhost` origins, or update `host_permissions` in manifest.json
- **Content script not loading** — Refresh the page; the extension injects into newly loaded pages
- **Service worker inactive** — Chrome may idle the service worker after ~30 seconds; clicking the popup or using the context menu reactivates it

## License

MIT
