# YouTube AI Analyzer

A Chrome side panel for evidence-aware YouTube analysis, guided watch plans, a live companion, study tools, visual insight extraction, and cross-video comparison. The FastAPI backend uses OpenRouter with Gemma for transcript reasoning and Qwen for video understanding.

## Model roles

- `google/gemma-4-31b-it:free` handles transcript analysis, questions about the current moment, watch plans, study sets, claim extraction, library comparisons, and web-grounded claim explanations.
- `qwen/qwen3.8-27b:free` handles slides, charts, diagrams, demonstrations, visual events, and spoken-versus-shown gaps.
- Qwen also acts as the structured-text fallback when Gemma's provider is temporarily unavailable.
- Video analysis does not fall back to Gemma because this Gemma endpoint does not accept video. Provider errors are returned directly so availability and account problems stay visible.
- Timestamp evidence is checked deterministically against the transcript after generation. A model cannot mark its own unsupported quote as verified.

## Local setup

Requires Python 3.12, Node.js, and an OpenRouter API key.

1. Install dependencies from the repository root: `python -m pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`.
3. Start the API: `cd backend`, then `uvicorn app.main:app --reload --port 8000`.
4. In another terminal run `cd extension`, `npm ci`, then `npm run build`.
5. In `chrome://extensions`, enable Developer mode and load `extension/dist` as an unpacked extension. Refresh open YouTube tabs after reloading it.

Check `http://127.0.0.1:8000/api/health` before analyzing a video. Run `python -m pytest -q` from the repository root for backend tests and `npm run lint` in `extension` for frontend linting.

OpenRouter currently requires an account balance for video inputs even when the selected model has a `:free` suffix. If visual analysis returns HTTP 402, add the balance requested by OpenRouter; quick transcript analysis continues to work without video input.

The free Gemma and Qwen providers use shared upstream capacity. An HTTP 429 with `temporarily rate-limited upstream` means both configured pools are busy, not that the deployment is broken. Retry later or connect your own Google/Qwen provider key in OpenRouter integrations for dedicated provider limits.

## Vercel deployment

The **backend** is the Vercel project. Import this repository and set its Root Directory to `backend`. Vercel discovers `app/main.py`, installs `backend/requirements.txt`, and uses the Python version in `backend/.python-version`.

Set these Vercel environment variables:

```text
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=google/gemma-4-31b-it:free
OPENROUTER_FALLBACK_MODEL=qwen/qwen3.8-27b:free
OPENROUTER_VIDEO_MODEL=qwen/qwen3.8-27b:free
OPENROUTER_VIDEO_FALLBACK_MODEL=
OPENROUTER_SITE_URL=https://YOUR-PROJECT.vercel.app
OPENROUTER_APP_NAME=YouTube AI Analyzer
OPENROUTER_REASONING_ENABLED=true
```

`CORS_ALLOWED_ORIGIN_REGEX` defaults to Chrome extension origins. Verify `https://YOUR-PROJECT.vercel.app/api/health` after deployment. The local `.env` file is never uploaded automatically.

For a CLI deployment, run `vercel link` and `vercel deploy --prod` inside `backend` after adding the environment variables to the linked Vercel project.

Build the extension against the deployed API:

```powershell
cd extension
$env:VITE_API_BASE_URL = "https://YOUR-PROJECT.vercel.app/api"
npm run build
```

The build adds the API origin to `dist/manifest.json` host permissions. Reload the unpacked extension and refresh the YouTube tab.

## Data and evidence

The API is stateless and suitable for Vercel Functions. The extension stores saved analyses, transcripts, and timestamped notes in extension-local IndexedDB; it does not sync them across devices. Compare sends the selected saved analyses and transcripts to the API only for that request.

`matched` means the quoted words occur near the generated timestamp. `uncertain` means nearby transcript exists but the quote did not match. `unsupported` means no nearby transcript supports it. These labels validate source alignment, not the truth of the overall conclusion. Claim Check separately invokes OpenRouter web search and remains `unchecked` unless source citations are returned.

Visual analysis sends a temporary direct YouTube video-stream URL plus sampled transcript context through OpenRouter. Public-video availability, YouTube stream restrictions, model availability, and OpenRouter account limits can affect that route. Protect a public deployment with appropriate Vercel rate limits or authentication because every request uses the server-side API key.

## API

- `GET /api/health`
- `POST /api/videos/analyze` with `url`, optional `transcript_data`, and `mode` (`quick` or `deep`)
- `POST /api/videos/{video_id}/ask` with `question`, optional `focus_time`, and optional `transcript_data`
- `GET /api/videos/{video_id}/transcript`
- `POST /api/videos/{video_id}/plan` with `goal`, `minutes`, transcript, and optional analysis
- `POST /api/videos/{video_id}/study` and `/claims` with transcript and optional analysis
- `POST /api/videos/{video_id}/visual` with optional transcript to add visual analysis
- `POST /api/claims/check` with `claim`
- `POST /api/videos/compare` with two to four saved video payloads and an optional question

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the request flow.
