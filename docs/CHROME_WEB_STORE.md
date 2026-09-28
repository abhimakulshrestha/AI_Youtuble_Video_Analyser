# Chrome Web Store Information

## Privacy and data usage

The extension sends the current public YouTube URL, available captions, and, during visual analysis, sampled player screenshots to the configured backend. The backend sends transcript text, screenshots, and individual claims to Groq for AI analysis or browser-search fact checking. The extension does not collect authentication tokens or unrelated browsing history.

Saved analyses, transcripts, and notes remain in extension-local IndexedDB on the current browser profile. Compare sends selected saved records to the backend only for that request.

## Permissions

- `activeTab` and YouTube host permissions: inspect the active video, retrieve available captions, follow playback, seek, and capture visible player frames for visual analysis.
- `scripting`: inject the same YouTube content script into an already-open video tab if Chrome has not loaded it yet.
- `sidePanel`: display the analyzer beside YouTube.
- Backend host permission: call the API selected at build time.

The extension communicates with YouTube and the configured backend. The backend communicates with YouTube and Groq. The Groq API key stays in the backend environment and is never packaged into the extension.

## Before public release

- Package the production `extension/dist` contents with `manifest.json` at the ZIP root; do not publish a development build pointing to localhost.
- Add a 128x128 extension icon, listing images, and a public privacy policy before Chrome Web Store submission.
- Complete the Web Store privacy disclosures for captions, screenshots, and local saved notes.
- Add user authentication or server-side rate limiting before a broad launch: the deployed API currently spends the owner's Groq quota for any caller.
