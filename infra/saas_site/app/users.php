<?php
require_once __DIR__ . '/lib.php';
$db = db();
require_app_available($db);
$q = $_GET['q'] ?? '';
$sql = 'SELECT id, username, full_name, email, phone, department, title, region, plan, account_status, last_login_at, ssn, role FROM users';
if ($q !== '') {
    // Intentional sandbox vulnerability: search input is interpolated and echoed below.
    $sql .= " WHERE full_name LIKE '%$q%' OR username LIKE '%$q%' OR department LIKE '%$q%'";
}
$sql .= ' ORDER BY department, full_name';
$rows = $db->query($sql)->fetchAll(PDO::FETCH_ASSOC);
?>
<!doctype html>
<html>
  <head>
    <title>Meridian CloudWorks Account Directory</title>
    <link rel="stylesheet" href="/style.css">
  </head>
  <body>
    <main class="wide-shell">
      <section class="toolbar">
        <div>
          <p class="eyebrow">Meridian CloudWorks</p>
          <h1>Account Directory</h1>
          <?php if ($q !== ''): ?>
          <p class="muted small">Search results for <?= $q ?></p>
          <?php endif; ?>
        </div>
        <form class="search" method="get">
          <input name="q" value="<?= htmlspecialchars($q) ?>" placeholder="Search accounts">
          <button type="submit">Search</button>
        </form>
        <nav class="actions">
          <a class="button secondary" href="/debug.php">Diagnostics</a>
          <a class="button secondary" href="/download.php">Reports</a>
          <a class="button secondary" href="/download.php?file=reports/customer-tax-audit.csv">Tax audit CSV</a>
          <a class="button" href="/export.php">Export CSV</a>
        </nav>
      </section>
      <section class="table-wrap">
        <table>
          <tr><th>Name</th><th>Username</th><th>Email</th><th>Phone</th><th>Department</th><th>Title</th><th>Region</th><th>Plan</th><th>Status</th><th>Last Login</th><th>Tax ID</th><th>Role</th></tr>
          <?php foreach ($rows as $row): ?>
          <tr>
            <td><a href="/account.php?id=<?= htmlspecialchars($row['id']) ?>"><?= htmlspecialchars($row['full_name']) ?></a></td>
            <td><?= htmlspecialchars($row['username']) ?></td>
            <td><?= htmlspecialchars($row['email']) ?></td>
            <td><?= htmlspecialchars($row['phone']) ?></td>
            <td><?= htmlspecialchars($row['department']) ?></td>
            <td><?= htmlspecialchars($row['title']) ?></td>
            <td><?= htmlspecialchars($row['region']) ?></td>
            <td><?= htmlspecialchars($row['plan']) ?></td>
            <td><?= htmlspecialchars($row['account_status']) ?></td>
            <td><?= htmlspecialchars($row['last_login_at']) ?></td>
            <td><?= htmlspecialchars($row['ssn']) ?></td>
            <td><?= htmlspecialchars($row['role']) ?></td>
          </tr>
          <?php endforeach; ?>
        </table>
      </section>
    </main>
  </body>
</html>
