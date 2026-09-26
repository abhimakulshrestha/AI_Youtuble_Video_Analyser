# Notebook Audit: `Youtube.ipynb`

Historical note: this document describes the original notebook and an earlier FAISS/SQLite design. The current deployable API is stateless; see `ARCHITECTURE.md` and the root `README.md`.

This document details the audit of the initial proof-of-concept Jupyter notebook, `Youtube.ipynb`, to inform the production-ready architecture.

## 1. Dependencies Used
- `youtube-transcript-api`: Used for fetching transcripts.
- `langchain-community`, `langchain-openai`: Core LLM integration and vector store wrappers.
- `faiss-cpu`: Local vector store for document embeddings.
- `tiktoken`: Tokenization for OpenAI models.
- `python-dotenv`: Environment variable management.

## 2. Processing Stages
1. **API Initialization**: Hardcoded OpenAI API key set in `os.environ`.
2. **Transcript Fetching**: `YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])`.
3. **Transcript Flattening**: The timestamped chunks are concatenated into a single plain text string.
4. **Chunking**: Uses `RecursiveCharacterTextSplitter` (1000 chunk size, 200 overlap) on the flattened string.
5. **Embedding & Storage**: OpenAI `text-embedding-3-small` embeddings stored in an in-memory `FAISS` index.
6. **Retrieval**: Configured as a similarity search with `k=4`.
7. **Q&A**: A `PromptTemplate` and `ChatOpenAI` (gpt-4o-mini) are used to answer questions based on the retrieved context. (Two approaches shown: manual formatting and LCEL `RunnableParallel` chain).

## 3. Identified Problems & Limitations

### Security Problems
- **Hardcoded API Keys**: The notebook contains a plaintext `OPENAI_API_KEY`. This is a critical security violation.
  *Fix*: The backend will use environment variables (e.g., `.env` file) for all secrets, which will never be exposed to the Chrome extension or frontend.

### Architectural & Scalability Limitations
- **Ephemeral FAISS**: The FAISS vector store is created entirely in-memory and discarded after the notebook stops.
  *Fix*: The backend will use persistent storage for FAISS indexes under a controlled data directory, segregated by `video_id`.
- **Single-Video Focus**: The notebook is hardcoded to a single video ID without support for dynamic inputs or caching.
  *Fix*: A robust REST API will handle dynamic video IDs, incorporating SQLite-backed caching for transcripts, analysis, and metadata.

### Data & Logic Flaws
- **Loss of Timestamp Information**: The transcript is flattened into a single string (`" ".join(chunk["text"] for chunk in transcript_list)`). This destroys the original `start` and `duration` metadata, making clickable timestamp citations impossible.
  *Fix*: We will implement a custom timestamp-aware chunking system that preserves start/end times and metadata for each chunk.
- **Flawed Summarization**: The notebook attempts to summarize the video using `retriever.invoke('Can you summarize the video')` with `k=4`. This only retrieves 4 chunks (around 4000 characters) matching the query, completely missing the vast majority of long videos.
  *Fix*: Summarization must be hierarchical or map-reduce based, reading through all chunks to synthesize a final structured summary representing the entire video.
- **Undefined Variables**: In one of the manual Q&A execution blocks (Cell 18), `context_text` is used in `prompt.invoke` before it is defined.

### Missing Robustness
- **Exception Handling**: There is only a basic `try/except` for `TranscriptsDisabled`. It lacks handling for network timeouts, unplayable videos, parsing errors, invalid IDs, or rate limits.
  *Fix*: Comprehensive error handling will be implemented at the API layer, returning standardized errors to the frontend.
- **Data Validation**: No validation ensures the provided video ID or URL is well-formed.
  *Fix*: Strict Pydantic-based URL parsing and validation will be used in the API.

## 4. Redesign Decisions
- **Retained**: The use of `youtube-transcript-api` (using updated methods), OpenAI embeddings, `FAISS` (but persisted), and `gpt-4o-mini`/`gpt-4o` for LLM tasks.
- **Replaced**: 
  - `RecursiveCharacterTextSplitter` on plain text is replaced by a custom token-aware chunker that aggregates subtitle dicts and preserves boundaries.
  - The single retrieval-based summarization approach is replaced by a structured, full-transcript recursive summarization pipeline.
- **Redesigned**: The entire application is split into a Chrome MV3 Extension (React/TypeScript) and a Python FastAPI backend. The backend will enforce structured JSON output for chapters, key points, and Q&A citations.
