<?php
require_once __DIR__ . '/lib.php';
$db = db();

require_app_available($db);

// Intentional sandbox vulnerability: unauthenticated diagnostic data exposure.
$keys = $db->query('SELECT owner_username, service, token, scope, created_at FROM api_keys ORDER BY service')->fetchAll(PDO::FETCH_ASSOC);
$userCount = intval($db->query('SELECT COUNT(*) FROM users')->fetchColumn());
?>
<!doctype html>
<html>
  <head>
    <title>Meridian CloudWorks Diagnostics</title>
    <link rel="stylesheet" href="/style.css">
  </head>
  <body>
    <main class="wide-shell">
      <section class="toolbar">
        <div>
          <p class="eyebrow">Meridian CloudWorks</p>
          <h1>Diagnostics</h1>
          <p class="muted small">Build and integration details for support escalations.</p>
        </div>
        <a class="button" href="/download.php">Latest renewal report</a>
      </section>
      <section class="panel wide-panel">
        <dl class="profile">
          <dt>Environment</dt><dd><?= htmlspecialchars(getenv('APP_ENV') ?: 'production') ?></dd>
          <dt>Database</dt><dd><?= htmlspecialchars(database_description()) ?></dd>
          <dt>PHP</dt><dd><?= htmlspecialchars(PHP_VERSION) ?></dd>
          <dt>User Accounts</dt><dd><?= htmlspecialchars((string) $userCount) ?></dd>
        </dl>
      </section>
      <section class="table-wrap">
        <table>
          <tr><th>Owner</th><th>Service</th><th>Token</th><th>Scope</th><th>Created</th></tr>
          <?php foreach ($keys as $key): ?>
          <tr>
            <td><?= htmlspecialchars($key['owner_username']) ?></td>
            <td><?= htmlspecialchars($key['service']) ?></td>
            <td><?= htmlspecialchars($key['token']) ?></td>
            <td><?= htmlspecialchars($key['scope']) ?></td>
            <td><?= htmlspecialchars($key['created_at']) ?></td>
          </tr>
          <?php endforeach; ?>
        </table>
      </section>
    </main>
  </body>
</html>
