const CACHE_NAME = 'rapid-1923-v1';

// Install – putem face pre-cache dacă vrei mai târziu
self.addEventListener('install', event => {
  self.skipWaiting();
});

// Activate – preia imediat controlul paginilor
self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});

// Fetch – încearcă rețeaua, dacă pică ia din cache (fallback simplu)
self.addEventListener('fetch', event => {
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});

// Push – afișează notificarea, fie din JSON, fie din text simplu
self.addEventListener('push', event => {
  let data = {};

  if (event.data) {
    try {
      // Cazul normal: serverul trimite JSON (json.dumps({...}) în Flask)
      data = event.data.json();
    } catch (e) {
      // Caz fallback: serverul trimite doar un string (ex. "Test push ...")
      const text = event.data.text();
      data = {
        title: 'Voluntari Rapid 1923',
        body: text,
        url: '/'
      };
    }
  }

  const title = data.title || 'Voluntari Rapid 1923';
  const options = {
    body: data.body || 'Notificare nouă',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    vibrate: [200, 100, 200],
    data: { url: data.url || '/' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Click pe notificare – deschide URL-ul din data.url
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow(event.notification.data.url)
  );
});