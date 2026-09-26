import type { TranscriptSegment, VideoAnalysis } from './api';

export interface SavedVideo {
  videoId: string;
  title: string;
  channel: string;
  analysis: VideoAnalysis;
  transcript: TranscriptSegment[];
  notes: { text: string; start: number; createdAt: string }[];
  savedAt: string;
}

const DB_NAME = 'youtube-analyzer-library';
const STORE = 'videos';

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'videoId' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function operation<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore, resolve: (value: T) => void, reject: (reason?: unknown) => void) => void): Promise<T> {
  return database().then(db => new Promise<T>((resolve, reject) => {
    const transaction = db.transaction(STORE, mode);
    let result: T;
    run(transaction.objectStore(STORE), value => { result = value; }, reject);
    transaction.oncomplete = () => { db.close(); resolve(result); };
    transaction.onerror = () => { db.close(); reject(transaction.error); };
  }));
}

export const library = {
  list: () => operation<SavedVideo[]>('readonly', (store, resolve, reject) => {
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result.sort((a, b) => b.savedAt.localeCompare(a.savedAt)));
    request.onerror = () => reject(request.error);
  }),
  get: (videoId: string) => operation<SavedVideo | undefined>('readonly', (store, resolve, reject) => {
    const request = store.get(videoId);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  }),
  put: (video: SavedVideo) => operation<void>('readwrite', (store, resolve, reject) => {
    const request = store.put(video);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  }),
  remove: (videoId: string) => operation<void>('readwrite', (store, resolve, reject) => {
    const request = store.delete(videoId);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  }),
};
