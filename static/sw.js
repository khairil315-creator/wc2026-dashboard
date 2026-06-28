self.addEventListener('install', function(e) {
  self.skipWaiting();
});
self.addEventListener('activate', function(e) {
  e.waitUntil(clients.claim());
});
self.addEventListener('push', function(e) {
  if (!e.data) return;
  const data = e.data.json();
  const opts = {
    body: data.body || '',
    icon: '/favicon.png',
    requireInteraction: true,
    tag: data.tag || 'wc2026',
  };
  e.waitUntil(self.registration.showNotification(data.title || 'WC2026', opts));
});
self.addEventListener('notificationclick', function(e) {
  e.notification.close();
  e.waitUntil(clients.openWindow('/'));
});
