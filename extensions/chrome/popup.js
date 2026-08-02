// Spacetime Memory Clipper - Popup Script

document.addEventListener('DOMContentLoaded', () => {
  const clipBtn = document.getElementById('clip-btn');
  const statusEl = document.getElementById('status');
  const pageTitle = document.getElementById('page-title');
  const pageUrl = document.getElementById('page-url');
  const badgeCount = document.getElementById('badge-count');
  const clipList = document.getElementById('clip-list');
  const toastContainer = document.getElementById('toast-container');
  const selectionIndicator = document.getElementById('selection-indicator');
  const selectionText = document.getElementById('selection-text');

  // Settings elements
  const settingsToggle = document.getElementById('settings-toggle');
  const settingsPanel = document.getElementById('settings-panel');
  const dbHostInput = document.getElementById('db-host');
  const dbIdentityInput = document.getElementById('db-identity');
  const workspaceIdInput = document.getElementById('workspace-id');
  const peerIdInput = document.getElementById('peer-id');
  const saveSettingsBtn = document.getElementById('save-settings');
  const saveStatus = document.getElementById('save-status');

  // ---------------------------------------------------------------
  // Load current tab info
  // ---------------------------------------------------------------
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs && tabs[0]) {
      const tab = tabs[0];
      pageTitle.textContent = tab.title || 'Untitled Page';
      pageUrl.textContent = tab.url || '';
    }
  });

  // ---------------------------------------------------------------
  // Load settings and clip count
  // ---------------------------------------------------------------
  function loadSettings() {
    chrome.runtime.sendMessage({ action: 'get-settings' }, (response) => {
      if (response) {
        dbHostInput.value = response.dbHost || 'localhost:3001';
        dbIdentityInput.value = response.dbIdentity || '';
        workspaceIdInput.value = response.workspaceId || '';
        peerIdInput.value = response.peerId || 'browser-extension';
      }
    });
  }

  function loadClipCount() {
    chrome.runtime.sendMessage({ action: 'get-clip-count' }, (response) => {
      if (response) {
        badgeCount.textContent = response.count || 0;
      }
    });
  }

  function loadClipHistory() {
    chrome.runtime.sendMessage({ action: 'get-clip-history' }, (response) => {
      if (response && response.history && response.history.length > 0) {
        renderClipHistory(response.history);
      }
    });
  }

  // ---------------------------------------------------------------
  // Check for selection on current page
  // ---------------------------------------------------------------
  function checkSelection() {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || !tabs[0]) return;
      chrome.tabs.sendMessage(tabs[0].id, { action: 'get-clip-data' }, (response) => {
        if (chrome.runtime.lastError) {
          // Content script not ready yet
          selectionIndicator.style.display = 'none';
          return;
        }
        if (response && response.selection) {
          selectionIndicator.style.display = 'flex';
          selectionText.textContent = `"${response.selection.substring(0, 60)}${response.selection.length > 60 ? '...' : ''}"`;
        } else {
          selectionIndicator.style.display = 'none';
        }
      });
    });
  }

  // ---------------------------------------------------------------
  // Clip button handler
  // ---------------------------------------------------------------
  clipBtn.addEventListener('click', () => {
    clipBtn.disabled = true;
    clipBtn.textContent = 'Clipping...';
    statusEl.textContent = '';
    statusEl.className = 'status';

    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || !tabs[0]) {
        showError('No active tab found');
        resetClipBtn();
        return;
      }

      const tab = tabs[0];

      // Check for selection first
      chrome.tabs.sendMessage(tab.id, { action: 'get-clip-data' }, (response) => {
        if (response && response.selection) {
          // Clip selection
          chrome.runtime.sendMessage({
            action: 'clip-selection',
            tab: tab,
            selection: response.selection
          });
          showToast('Clipping selected text...', 'info');
        } else {
          // Clip full page
          chrome.runtime.sendMessage({
            action: 'clip-page',
            tab: tab
          });
          showToast('Clipping page...', 'info');
        }
      });
    });

    // Reset button after a delay
    setTimeout(resetClipBtn, 3000);
  });

  function resetClipBtn() {
    clipBtn.disabled = false;
    clipBtn.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
      </svg>
      Clip Page to Memory
    `;
  }

  // ---------------------------------------------------------------
  // Toast notification system
  // ---------------------------------------------------------------
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(() => {
      toast.classList.add('toast-visible');
    });

    // Auto-remove after 3s
    setTimeout(() => {
      toast.classList.remove('toast-visible');
      toast.classList.add('toast-hiding');
      setTimeout(() => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 300);
    }, 3000);
  }

  function showSuccess(msg) {
    showToast(msg, 'success');
  }

  function showError(msg) {
    showToast(msg, 'error');
  }

  // ---------------------------------------------------------------
  // Render clip history
  // ---------------------------------------------------------------
  function renderClipHistory(history) {
    // Show last 5
    const recent = history.slice(0, 5);
    clipList.innerHTML = '';

    if (recent.length === 0) {
      clipList.innerHTML = '<div class="clip-list-empty">No clips yet. Start clipping pages!</div>';
      return;
    }

    recent.forEach((entry) => {
      const item = document.createElement('div');
      item.className = `clip-item ${entry.success ? '' : 'clip-item-error'}`;
      const icon = entry.success ? '✓' : '✗';
      const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : '';
      item.innerHTML = `
        <div class="clip-item-icon">${icon}</div>
        <div class="clip-item-info">
          <div class="clip-item-title">${escapeHtml(entry.title || 'Untitled')}</div>
          <div class="clip-item-meta">${escapeHtml(entry.url || '')} · ${time}</div>
        </div>
      `;
      clipList.appendChild(item);
    });
  }

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ---------------------------------------------------------------
  // Settings toggle
  // ---------------------------------------------------------------
  settingsToggle.addEventListener('click', () => {
    const isVisible = settingsPanel.style.display !== 'none';
    settingsPanel.style.display = isVisible ? 'none' : 'block';
    const chevron = settingsToggle.querySelector('.chevron');
    if (chevron) {
      chevron.style.transform = isVisible ? 'rotate(0deg)' : 'rotate(90deg)';
    }
  });

  // ---------------------------------------------------------------
  // Save settings
  // ---------------------------------------------------------------
  saveSettingsBtn.addEventListener('click', () => {
    const settings = {
      dbHost: dbHostInput.value.trim(),
      dbIdentity: dbIdentityInput.value.trim(),
      workspaceId: workspaceIdInput.value.trim(),
      peerId: peerIdInput.value.trim()
    };

    chrome.runtime.sendMessage({ action: 'save-settings', settings }, (response) => {
      if (response && response.success) {
        saveStatus.textContent = '✓ Settings saved';
        saveStatus.className = 'save-status save-status-success';
        showToast('Settings saved', 'success');
      } else {
        saveStatus.textContent = '✗ Failed to save settings';
        saveStatus.className = 'save-status save-status-error';
      }
      setTimeout(() => {
        saveStatus.textContent = '';
        saveStatus.className = 'save-status';
      }, 3000);
    });
  });

  // ---------------------------------------------------------------
  // Listen for clip results from background
  // ---------------------------------------------------------------
  chrome.runtime.onMessage.addListener((message) => {
    switch (message.action) {
      case 'clip-result':
        if (message.success) {
          showSuccess('✓ Clipped successfully!');
          loadClipCount();
          // Reload history after a short delay
          setTimeout(loadClipHistory, 500);
        } else {
          showError(`✗ ${message.error || 'Clip failed'}`);
        }
        break;
      default:
        break;
    }
  });

  // ---------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------
  loadSettings();
  loadClipCount();
  loadClipHistory();
  setTimeout(checkSelection, 500);
});
