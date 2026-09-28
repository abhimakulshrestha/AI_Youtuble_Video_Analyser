void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(console.error);

chrome.action.onClicked.addListener((tab) => {
  if (tab.id !== undefined) {
    void chrome.sidePanel.open({ tabId: tab.id }).catch(console.error);
  }
});

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
