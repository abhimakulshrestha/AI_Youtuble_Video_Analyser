# YouTube AI Analyzer

A Chrome side panel for transcript analysis, goal-based watch plans, a live companion, a local knowledge library, visual insights, evidence timelines, claim checks, video comparisons, and study tools.

## Models and evidence

- Groq `openai/gpt-oss-20b` handles transcript analysis, Q&A, plans, study sets, claim extraction, and comparisons. `qwen/qwen3.8-27b` is its text fallback.
- Groq Qwen analyzes timestamped screenshots captured from the visible YouTube player. It does not receive or decode a YouTube URL as video. Visual analysis samples three frames; it cannot see every moment. The extension temporarily seeks through the video and restores playback afterward.
- Groq GPT-OSS browser search checks individual claims against outside sources. Unchecked claims are labeled as such. Transcript evidence labels indicate quote/timestamp alignment, not independent factual truth.
- For long videos, the backend spreads transcript excerpts across the full timeline to stay within Groq's input-token limit and shows a coverage warning. Short videos use the full transcript.

## Local setup

Requires Python 3.12, Node.js, and a Groq API key.

1. Run `python -m pip install -r requirements-dev.txt` from the repository root.
2. Copy `.env.example` to `.env` and set `GROQ_API_KEY`.
3. Start the API with `cd backend` and `uvicorn app.main:app --reload --port 8000`.
4. In another terminal, run `cd extension`, `npm ci`, then `npm run build -- --mode development` to target the local API. Plain `npm run build` targets the deployed API configured in `extension/.env.production`.
5. In `chrome://extensions`, enable Developer mode and load `extension/dist` unpacked. Reload the extension and refresh YouTube tabs after rebuilding.

Check `http://127.0.0.1:8000/api/health`. Run `python -m pytest -q` and `cd extension; npm run lint; npm run build` for local checks. A live Groq request is still needed to prove provider availability; HTTP 429 may mean a model-specific rate limit. Qwen's free-tier image input limit is especially tight, so repeated visual scans may require a wait.

## Vercel

The repository root is the Vercel project root. Root `main.py` exposes the FastAPI app and root `requirements.txt` installs dependencies. Set **Production** `GROQ_API_KEY` in the Vercel project; `.env` stays local. Optional model variables are shown in `.env.example`. Redeploy after changing environment variables, then check `https://YOUR-PROJECT.vercel.app/api/health` and make a real analysis request.

The extension build must use the deployed API URL in `VITE_API_BASE_URL`, for example `https://YOUR-PROJECT.vercel.app/api`; the build adds that origin to its host permissions. Do not put `GROQ_API_KEY` in the extension. The API is public and uses the server-side key, so add authentication or rate limiting before broad distribution.

Vercel deploys only the API. To share the extension with testers, run `cd extension; npm ci; npm run build` and zip the **contents** of `extension/dist` (with `manifest.json` at the ZIP root). Testers can extract it and load that folder through Chrome's `chrome://extensions` Developer mode. For general installation, publish the same production build through the Chrome Web Store after preparing required icons, listing, privacy disclosures, and review. Never share a development build, which points to localhost.

The backend is stateless. Saved videos, transcripts, and notes stay in extension-local IndexedDB on this browser profile. Compare sends selected saved material to the API for that request; cross-device syncing is not implemented.

## API

- `GET /api/health`
- `POST /api/videos/analyze` with `url` and optional `transcript_data`
- `POST /api/videos/{video_id}/ask` with `question`, optional `focus_time` and `transcript_data`
- `POST /api/videos/{video_id}/plan`, `/study`, `/claims`, and `/visual`
- `POST /api/claims/check`
- `POST /api/videos/compare`

See [architecture](docs/ARCHITECTURE.md) and [Chrome Web Store privacy notes](docs/CHROME_WEB_STORE.md).
