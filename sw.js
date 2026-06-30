const CACHE_NAME = 'roastia-v1';
const CACHE_STATIC = 'roastia-static-v1';

// 初回キャッシュするリソース
const PRECACHE = [
  '/',
  '/index.html',
  '/favorites.html',
  '/shops-lite.json',
  'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js',
  'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css',
  'https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js',
  'https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.css',
  'https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css',
  'https://cdn.jsdelivr.net/npm/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.js',
  'https://cdn.jsdelivr.net/npm/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.css',
  'https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js',
  'https://www.gstatic.com/firebasejs/10.12.0/firebase-auth-compat.js',
  'https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore-compat.js',
];

// インストール: 静的リソースを事前キャッシュ
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_STATIC).then(cache => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

// アクティベート: 古いキャッシュを削除
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME && k !== CACHE_STATIC).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// フェッチ戦略
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Firebase Auth/Firestore のAPIリクエストはキャッシュしない
  if (url.hostname.includes('firestore.googleapis.com') ||
      url.hostname.includes('firebase') ||
      url.hostname.includes('cloudinary') ||
      url.hostname.includes('nominatim') ||
      url.hostname.includes('router.project-osrm') ||
      e.request.method !== 'GET') {
    return;
  }

  // shops-full.json: キャッシュファースト（バックグラウンドで更新）
  if (url.pathname.endsWith('shops-full.json')) {
    e.respondWith(staleWhileRevalidate(e.request));
    return;
  }

  // shops-lite.json: キャッシュファースト（バックグラウンドで更新）
  if (url.pathname.endsWith('shops-lite.json')) {
    e.respondWith(staleWhileRevalidate(e.request));
    return;
  }

  // HTML: ネットワークファースト（オフライン時はキャッシュ）
  if (e.request.headers.get('accept')?.includes('text/html')) {
    e.respondWith(
      fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // その他（JS/CSS/画像）: キャッシュファースト
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE_STATIC).then(c => c.put(e.request, clone));
        }
        return res;
      });
    })
  );
});

// Stale-While-Revalidate: キャッシュをすぐ返しつつ裏で更新
function staleWhileRevalidate(request) {
  return caches.open(CACHE_NAME).then(cache =>
    cache.match(request).then(cached => {
      const fresh = fetch(request).then(res => {
        if (res.ok) cache.put(request, res.clone());
        return res;
      });
      return cached || fresh;
    })
  );
}
