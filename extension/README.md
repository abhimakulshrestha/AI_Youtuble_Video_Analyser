# Chrome extension

Run `npm ci`, then `npm run build`. Load `extension/dist` at `chrome://extensions` as an unpacked extension. The default API is `http://127.0.0.1:8000/api`.

To use a deployed API, set `VITE_API_BASE_URL` to its full `/api` URL before building. The Vite build adds that URL's origin to the packaged Chrome host permissions. See the repository [README](../README.md) for the full Vercel steps.
