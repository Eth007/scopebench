<?php
require_once __DIR__ . '/lib.php';

$db = db();
if (!startup_ready()) {
    fwrite(STDERR, "app still starting\n");
    exit(1);
}
if (outage_active($db)) {
    fwrite(STDERR, "maintenance mode active\n");
    exit(1);
}
$count = intval($db->query('SELECT COUNT(*) FROM users')->fetchColumn());
if ($count < 50) {
    fwrite(STDERR, "seed data missing\n");
    exit(1);
}
exit(0);
?>
