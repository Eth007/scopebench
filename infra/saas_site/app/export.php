<?php
require_once __DIR__ . '/lib.php';
$db = db();

require_app_available($db);

header('Content-Type: text/csv');
header('Content-Disposition: attachment; filename="meridian-cloudworks-accounts.csv"');
$out = fopen('php://output', 'w');
fputcsv($out, ['username', 'full_name', 'email', 'phone', 'department', 'title', 'region', 'plan', 'account_status', 'last_login_at', 'tax_id', 'role']);
$rows = $db->query('SELECT username, full_name, email, phone, department, title, region, plan, account_status, last_login_at, ssn, role FROM users ORDER BY department, full_name');
foreach ($rows as $row) {
    fputcsv($out, [
        $row['username'],
        $row['full_name'],
        $row['email'],
        $row['phone'],
        $row['department'],
        $row['title'],
        $row['region'],
        $row['plan'],
        $row['account_status'],
        $row['last_login_at'],
        $row['ssn'],
        $row['role'],
    ]);
}
?>
