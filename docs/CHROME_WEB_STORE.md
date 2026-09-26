# Chrome Web Store Information

## Privacy & Data Usage

This extension sends the current public YouTube video URL and, when available, its captions to the backend selected at build time. The backend sends transcript content and temporary public-video stream URLs to OpenRouter for AI analysis. Claim Check can also send an individual claim to OpenRouter's web-search tool. The extension does not collect authentication tokens or unrelated browsing history.

Saved video analyses, transcripts, and notes are kept in Chrome extension-local IndexedDB. They remain on the current browser profile unless the user explicitly invokes a feature that sends them to the configured backend, such as Compare.

### Why permissions are needed

- `activeTab` and YouTube host permissions: read the active video context, retrieve public captions, follow playback, and seek to user-selected evidence timestamps.
- `sidePanel`: display the analyzer beside the YouTube player.
- Backend host permission: call the API selected at extension build time.

### External Servers

The extension communicates only with YouTube and the configured backend. The backend communicates with YouTube and OpenRouter. No third-party tracking scripts or CDNs are embedded in the extension.

The OpenRouter API key is stored only in the backend environment and is never packaged into or returned to the Chrome extension.
