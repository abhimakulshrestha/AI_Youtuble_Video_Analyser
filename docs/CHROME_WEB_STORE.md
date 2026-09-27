# Chrome Web Store Information

## Privacy and data usage

The extension sends the current public YouTube URL, available captions, and, during deep analysis, sampled player screenshots to the configured backend. The backend sends transcript text, screenshots, and individual claims to Groq for AI analysis or browser-search fact checking. The extension does not collect authentication tokens or unrelated browsing history.

Saved analyses, transcripts, and notes remain in extension-local IndexedDB on the current browser profile. Compare sends selected saved records to the backend only for that request.

## Permissions

- `activeTab` and YouTube host permissions: inspect the active video, retrieve available captions, follow playback, seek, and capture visible player frames for deep analysis.
- `sidePanel`: display the analyzer beside YouTube.
- Backend host permission: call the API selected at build time.

The extension communicates with YouTube and the configured backend. The backend communicates with YouTube and Groq. The Groq API key stays in the backend environment and is never packaged into the extension.
