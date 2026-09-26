// Allow side panel to open on action click
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((error: any) => console.error(error));

chrome.tabs.onUpdated.addListener((tabId: number, info: any, tab: chrome.tabs.Tab) => {
  if (info.url && tab.url?.includes('youtube.com/watch')) {
    // Notify side panel or content script that the URL changed
    chrome.runtime.sendMessage({
      type: 'VIDEO_CHANGED',
      url: info.url,
      tabId: tabId
    }).catch(() => {
      // Ignore errors if no listeners
    });
  }
});
