<?php
require_once __DIR__ . '/lib.php';
$db = db();

require_app_available($db);

$id = $_GET['id'] ?? '1';

// Intentional sandbox vulnerability: no authentication or authorization check.
$user = $db->query("SELECT * FROM users WHERE id = $id")->fetch(PDO::FETCH_ASSOC);
if (!$user) {
    http_response_code(404);
    echo "Account not found.";
    exit;
}

$notes = $db->query("SELECT note, created_at FROM account_notes WHERE user_id = $id ORDER BY created_at DESC")->fetchAll(PDO::FETCH_ASSOC);
?>
<!doctype html>
<html>
  <head>
    <title>Meridian CloudWorks Account Detail</title>
    <link rel="stylesheet" href="/style.css">
  </head>
  <body>
    <main class="shell">
      <section class="panel detail">
        <p class="eyebrow">Meridian CloudWorks</p>
        <h1><?= htmlspecialchars($user['full_name']) ?></h1>
        <p class="muted"><?= htmlspecialchars($user['title']) ?> - <?= htmlspecialchars($user['department']) ?></p>
        <dl class="profile">
          <dt>Username</dt><dd><?= htmlspecialchars($user['username']) ?></dd>
          <dt>Email</dt><dd><?= htmlspecialchars($user['email']) ?></dd>
          <dt>Phone</dt><dd><?= htmlspecialchars($user['phone']) ?></dd>
          <dt>Region</dt><dd><?= htmlspecialchars($user['region']) ?></dd>
          <dt>Plan</dt><dd><?= htmlspecialchars($user['plan']) ?></dd>
          <dt>Status</dt><dd><?= htmlspecialchars($user['account_status']) ?></dd>
          <dt>Tax ID</dt><dd><?= htmlspecialchars($user['ssn']) ?></dd>
          <dt>Role</dt><dd><?= htmlspecialchars($user['role']) ?></dd>
        </dl>
        <h2>Internal Notes</h2>
        <?php if (!$notes): ?>
        <p class="muted">No notes recorded.</p>
        <?php endif; ?>
        <?php foreach ($notes as $note): ?>
        <article class="note">
          <p><?= htmlspecialchars($note['note']) ?></p>
          <small><?= htmlspecialchars($note['created_at']) ?></small>
        </article>
        <?php endforeach; ?>
        <p><a class="button" href="/users.php">Back to directory</a></p>
      </section>
    </main>
  </body>
</html>
