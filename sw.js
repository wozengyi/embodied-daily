const CACHE_NAME = 'embodied-daily-v1';
const ASSETS = [
  './',
  './index.html',
  './styles.css',
  './app.js',
  './papers.js',
  './data/data.js',
  './manifest.json',
  './icon.svg'
];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  if(e.request.method !== 'GET') return;
  e.respondWith(fetch(e.request).then(response => {
    const copy = response.clone();
    caches.open(CACHE_NAME).then(cache => cache.put(e.request, copy));
    return response;
  }).catch(() => caches.match(e.request)));
});
