// Spacetime Memory Clipper - Content Script
// Injected into web pages to capture selections and page data

let currentSelection = '';
let fullPageText = '';

// Track selection changes
document.addEventListener('selectionchange', () => {
  const sel = window.getSelection();
  currentSelection = sel ? sel.toString().trim() : '';
});

// Listen for messages from background script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.action) {
    case 'get-clip-data':
      sendResponse({
        url: window.location.href,
        title: document.title,
        selection: currentSelection,
        fullText: getPageText()
      });
      break;
    default:
      break;
  }
});

// Helper: extract readable page text
function getPageText() {
  if (fullPageText) return fullPageText;

  try {
    const body = document.body;
    const clone = body.cloneNode(true);
    clone.querySelectorAll('script, style, noscript, svg, iframe, canvas, video, audio').forEach(el => el.remove());
    fullPageText = clone.innerText.trim().substring(0, 100000);
    return fullPageText;
  } catch (e) {
    return document.body?.innerText?.substring(0, 100000) || '';
  }
}

// Notify background that we're ready
chrome.runtime.sendMessage({ action: 'content-script-ready', url: window.location.href });
