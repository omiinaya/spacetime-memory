// Spacetime Memory Clipper - Background Service Worker

let clipCount = 0;
const MAX_CLIP_HISTORY = 50;

// Load persisted state on startup
chrome.storage.local.get(['clipCount', 'clipHistory'], (result) => {
  if (result.clipCount) clipCount = result.clipCount;
  updateBadge();
});

// ---------------------------------------------------------------
// Context Menus
// ---------------------------------------------------------------
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'clip-page',
    title: 'Clip Page to Spacetime Memory',
    contexts: ['page']
  });
  chrome.contextMenus.create({
    id: 'clip-selection',
    title: 'Clip Selection to Spacetime Memory',
    contexts: ['selection']
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'clip-page') {
    handleClipPage(tab);
  } else if (info.menuItemId === 'clip-selection') {
    handleClipSelection(tab, info.selectionText);
  }
});

// ---------------------------------------------------------------
// Keyboard command
// ---------------------------------------------------------------
chrome.commands.onCommand.addListener((command) => {
  if (command === 'clip-to-memory') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) handleClipPage(tabs[0]);
    });
  }
});

// ---------------------------------------------------------------
// Message handlers from popup / content script
// ---------------------------------------------------------------
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.action) {
    case 'clip-page':
      handleClipPage(message.tab || null);
      break;
    case 'clip-selection':
      handleClipSelection(message.tab || null, message.selection);
      break;
    case 'get-clip-count':
      sendResponse({ count: clipCount });
      break;
    case 'get-clip-history':
      sendResponse({ history: getClipHistory() });
      break;
    case 'get-settings':
      chrome.storage.local.get(['dbHost', 'dbIdentity', 'workspaceId', 'peerId'], (result) => {
        sendResponse({
          dbHost: result.dbHost || 'localhost:3001',
          dbIdentity: result.dbIdentity || '',
          workspaceId: result.workspaceId || '',
          peerId: result.peerId || 'browser-extension'
        });
      });
      return true; // keep channel open for async response
    case 'save-settings':
      chrome.storage.local.set({
        dbHost: message.settings.dbHost,
        dbIdentity: message.settings.dbIdentity,
        workspaceId: message.settings.workspaceId,
        peerId: message.settings.peerId
      });
      sendResponse({ success: true });
      break;
    default:
      break;
  }
});

// ---------------------------------------------------------------
// Core clipping function
// ---------------------------------------------------------------
async function clipToMemory({ url, title, content, selection, workspaceId, peerId, dbHost, dbIdentity }) {
  if (!dbHost || !dbIdentity || !workspaceId) {
    throw new Error('Missing configuration. Please set DB host, database identity, and workspace ID in the extension settings.');
  }

  // Build the payload body as an array matching the store_memory function signature
  const body = JSON.stringify([
    workspaceId,           // workspace_id
    peerId,                // peer_id
    '',                    // observer_id
    'experience',          // memory_type
    content || url,        // content (page content or URL)
    title,                 // summary (page title)
    '[]',                  // entities_json
    0.8,                   // confidence
    '',                    // source_session_id
    '',                    // source_message_id
    ''                     // images_json
  ]);

  const endpoint = `http://${dbHost}/v1/database/${dbIdentity}/call/store_memory`;

  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: body
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API error ${response.status}: ${errorText}`);
  }

  const result = await response.json();
  return result;
}

// ---------------------------------------------------------------
// Handle clipping a page
// ---------------------------------------------------------------
function handleClipPage(tab) {
  if (!tab) {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) doClipPage(tabs[0]);
    });
  } else {
    doClipPage(tab);
  }
}

function doClipPage(tab) {
  // Inject content script if needed, then get full page text
  chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      // Get all visible text
      const body = document.body;
      const clone = body.cloneNode(true);
      // Remove script/style elements from clone
      clone.querySelectorAll('script, style, noscript, svg, iframe').forEach(el => el.remove());
      return clone.innerText.trim().substring(0, 100000); // limit to 100k chars
    }
  }).then((results) => {
    const pageText = results[0]?.result || '';
    performClip(tab.url, tab.title || '', pageText, '', tab.id);
  }).catch((err) => {
    // Fallback: clip without full text
    performClip(tab.url, tab.title || '', tab.url, '', tab.id);
  });
}

// ---------------------------------------------------------------
// Handle clipping a selection
// ---------------------------------------------------------------
function handleClipSelection(tab, selectionText) {
  if (!tab) {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) doClipSelection(tabs[0], selectionText);
    });
  } else {
    doClipSelection(tab, selectionText);
  }
}

function doClipSelection(tab, selectionText) {
  performClip(tab.url, tab.title || '', selectionText, selectionText, tab.id);
}

// ---------------------------------------------------------------
// Perform the actual API call and handle result
// ---------------------------------------------------------------
function performClip(url, title, content, selection, tabId) {
  chrome.storage.local.get(['dbHost', 'dbIdentity', 'workspaceId', 'peerId'], async (settings) => {
    const dbHost = settings.dbHost || 'localhost:3001';
    const dbIdentity = settings.dbIdentity || '';
    const workspaceId = settings.workspaceId || '';
    const peerId = settings.peerId || 'browser-extension';

    try {
      const result = await clipToMemory({
        url,
        title,
        content,
        selection,
        workspaceId,
        peerId,
        dbHost,
        dbIdentity
      });

      // Increment clip count
      clipCount++;
      chrome.storage.local.set({ clipCount });
      updateBadge();

      // Add to history
      addToHistory({ url, title, timestamp: Date.now(), success: true });

      // Show notification
      chrome.notifications.create({
        type: 'basic',
        iconUrl: 'icons/icon128.png',
        title: 'Spacetime Memory',
        message: `✓ Clipped: "${title.substring(0, 80)}"`,
        priority: 1
      });

      // Notify popup if open
      chrome.runtime.sendMessage({ action: 'clip-result', success: true, result }).catch(() => {});

    } catch (error) {
      // Add to history (with error)
      addToHistory({ url, title, timestamp: Date.now(), success: false, error: error.message });

      // Show error notification
      chrome.notifications.create({
        type: 'basic',
        iconUrl: 'icons/icon128.png',
        title: 'Spacetime Memory - Error',
        message: `✗ ${error.message}`,
        priority: 2
      });

      chrome.runtime.sendMessage({ action: 'clip-result', success: false, error: error.message }).catch(() => {});
    }
  });
}

// ---------------------------------------------------------------
// Badge update
// ---------------------------------------------------------------
function updateBadge() {
  if (clipCount > 0) {
    chrome.action.setBadgeText({ text: String(clipCount) });
    chrome.action.setBadgeBackgroundColor({ color: '#6366f1' });
  } else {
    chrome.action.setBadgeText({ text: '' });
  }
}

// ---------------------------------------------------------------
// Clip history management
// ---------------------------------------------------------------
function addToHistory(entry) {
  chrome.storage.local.get(['clipHistory'], (result) => {
    let history = result.clipHistory || [];
    history.unshift(entry);
    if (history.length > MAX_CLIP_HISTORY) {
      history = history.slice(0, MAX_CLIP_HISTORY);
    }
    chrome.storage.local.set({ clipHistory: history });
  });
}

function getClipHistory() {
  // Synchronous read from local cache - for popup we'll do async
  return [];
}

// Export for module loading (service worker)
if (typeof self !== 'undefined') {
  self.clipToMemory = clipToMemory;
}
