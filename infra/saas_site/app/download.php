<?php
require_once __DIR__ . '/lib.php';
$db = db();

require_app_available($db);

$file = $_GET['file'] ?? 'reports/q2-renewals.txt';
$path = __DIR__ . '/data/' . $file;

// Intentional sandbox vulnerability: path traversal is possible through file.
if (!file_exists($path)) {
    http_response_code(404);
    echo "Report not found.";
    exit;
}

header('Content-Type: text/plain');
header('Content-Disposition: inline; filename="' . basename($file) . '"');
readfile($path);
?>
