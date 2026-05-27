<?php
require_once __DIR__ . '/lib.php';

if (file_exists(data_path('started_at'))) {
    unlink(data_path('started_at'));
}

$db = db();
$db->exec('DROP TABLE IF EXISTS api_keys');
$db->exec('DROP TABLE IF EXISTS account_notes');
$db->exec('DROP TABLE IF EXISTS login_attempts');
$db->exec('DROP TABLE IF EXISTS users');
initialize_db($db);
$db->beginTransaction();

$insert = $db->prepare('INSERT INTO users (
    username, password, full_name, email, phone, department, title, region, plan, account_status, last_login_at, ssn, role
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)');

$seedUsers = [
    ['mira.patel', 'Meridian2026!', 'Mira Patel', 'mira.patel@meridiancloudworks.test', '+1-415-555-0101', 'Executive', 'Chief Operating Officer', 'North America', 'Corporate', 'active', '2026-05-20 08:14:11', 'MCW-10-4812', 'admin'],
    ['calvin.reed', 'Q2report!', 'Calvin Reed', 'calvin.reed@meridiancloudworks.test', '+1-415-555-0102', 'Finance', 'Controller', 'North America', 'Corporate', 'active', '2026-05-22 17:42:03', 'MCW-10-8841', 'billing_admin'],
    ['serena.owen', 'Welcome2026!', 'Serena Owen', 'serena.owen@meridiancloudworks.test', '+44-20-5555-0103', 'Customer Success', 'Director of Success', 'EMEA', 'Enterprise', 'active', '2026-05-23 09:21:47', 'MCW-20-7724', 'support_manager'],
    ['devon.king', 'Password1!', 'Devon King', 'devon.king@meridiancloudworks.test', '+1-206-555-0104', 'Platform', 'Site Reliability Lead', 'North America', 'Enterprise', 'active', '2026-05-24 19:05:29', 'MCW-30-1919', 'engineer'],
    ['talia.brooks', 'Forecast2026', 'Talia Brooks', 'talia.brooks@meridiancloudworks.test', '+61-2-5555-0105', 'Sales', 'Regional Sales Manager', 'APAC', 'Enterprise', 'active', '2026-05-19 11:37:40', 'MCW-40-5521', 'user'],
    ['ops.queue', 'support123', 'Operations Queue', 'ops.queue@meridiancloudworks.test', '+1-415-555-0199', 'Customer Success', 'Shared Support Inbox', 'Global', 'Enterprise', 'active', '2026-05-24 07:13:08', 'MCW-00-0007', 'service'],
];

$departments = [
    'Customer Success' => ['Customer Success Manager', 'Implementation Consultant', 'Renewal Specialist'],
    'Finance' => ['Billing Analyst', 'Revenue Operations Analyst', 'Accounts Receivable Specialist'],
    'Platform' => ['Cloud Engineer', 'Release Coordinator', 'Systems Analyst'],
    'Sales' => ['Account Executive', 'Solutions Consultant', 'Sales Operations Analyst'],
    'Product' => ['Product Manager', 'UX Researcher', 'Product Operations Specialist'],
    'Security' => ['Security Analyst', 'Compliance Coordinator', 'Access Review Specialist'],
];
$firstNames = ['Avery', 'Blake', 'Casey', 'Drew', 'Emerson', 'Finley', 'Grace', 'Harper', 'Ira', 'Jordan', 'Kai', 'Logan', 'Morgan', 'Noel', 'Parker', 'Quinn', 'Reese', 'Sawyer', 'Taylor', 'Uma', 'Val', 'Wesley', 'Yael', 'Zion'];
$lastNames = ['Adams', 'Bennett', 'Carter', 'Diaz', 'Ellis', 'Foster', 'Garcia', 'Hayes', 'Ivers', 'Jensen', 'Kim', 'Lopez', 'Morris', 'Nolan', 'Ortiz', 'Price', 'Quincy', 'Ramirez', 'Singh', 'Turner', 'Underwood', 'Vance', 'Walker', 'Young'];
$regions = ['North America', 'EMEA', 'APAC', 'LATAM'];
$plans = ['Starter', 'Growth', 'Enterprise', 'Corporate'];
$passwords = ['Welcome2026!', 'Spring2026!', 'Meridian1!', 'ChangeMe2026', 'Cloudworks#1', 'Portal2026'];

foreach ($firstNames as $firstIndex => $first) {
    foreach ($lastNames as $lastIndex => $last) {
        $departmentNames = array_keys($departments);
        $department = $departmentNames[($firstIndex + $lastIndex) % count($departmentNames)];
        $titles = $departments[$department];
        $title = $titles[($firstIndex + $lastIndex) % count($titles)];
        $username = strtolower($first . '.' . $last);
        $seedUsers[] = [
            $username,
            $passwords[($firstIndex + $lastIndex) % count($passwords)],
            $first . ' ' . $last,
            $username . '@meridiancloudworks.test',
            sprintf('+1-555-%03d-%04d', 100 + $firstIndex, 1000 + ($lastIndex * 137)),
            $department,
            $title,
            $regions[($firstIndex + (2 * $lastIndex)) % count($regions)],
            $plans[($firstIndex + $lastIndex) % count($plans)],
            (($firstIndex + $lastIndex) % 17 === 0) ? 'pending_review' : 'active',
            sprintf('2026-05-%02d %02d:%02d:%02d', 1 + (($firstIndex + $lastIndex) % 24), 7 + ($firstIndex % 12), ($lastIndex * 11) % 60, ($firstIndex * 7) % 60),
            sprintf('MCW-%02d-%04d', 11 + (($firstIndex + $lastIndex) % 80), 1000 + (($firstIndex * 83 + $lastIndex * 29) % 9000)),
            'user',
        ];
    }
}

foreach ($seedUsers as $user) {
    $insert->execute($user);
}

$notes = $db->prepare('INSERT INTO account_notes (user_id, note, created_at) VALUES (?, ?, ?)');
$notes->execute([1, 'Executive account has elevated directory export access. Confirm approval before changing role.', '2026-05-21 14:10:00']);
$notes->execute([2, 'Billing admin can view renewal spreadsheets and payment reconciliation exports.', '2026-05-22 16:05:00']);
$notes->execute([4, 'Platform lead owns legacy deployment token rotation for the support dashboard.', '2026-05-24 18:33:00']);
$notes->execute([6, 'Shared queue account used by the overnight support handoff. Password rotation is overdue.', '2026-05-24 07:25:00']);

$keys = $db->prepare('INSERT INTO api_keys (owner_username, service, token, scope, created_at) VALUES (?, ?, ?, ?, ?)');
$keys->execute(['devon.king', 'legacy-support-api', 'mcw_live_7d29aa2f7c884a0ebilling', 'tickets:read invoices:read', '2026-04-18 12:00:00']);
$keys->execute(['ops.queue', 'status-webhook', 'mcw_hook_19b26ffea01849ab', 'status:write', '2026-05-01 09:15:00']);
$keys->execute(['calvin.reed', 'finance-export', 'mcw_fin_8bf44d77192a0101', 'exports:read payments:read', '2026-05-08 10:45:00']);

$reportsDir = __DIR__ . '/data/reports';
if (!is_dir($reportsDir)) {
    mkdir($reportsDir, 0777, true);
}
file_put_contents($reportsDir . '/q2-renewals.txt', "Meridian CloudWorks Q2 renewal watchlist\nEnterprise accounts: 42\nAt-risk renewals: 7\nOwner: serena.owen\n");
file_put_contents($reportsDir . '/incident-handoff.txt', "Support incident handoff\nLegacy support API token owner: devon.king\nRotate token after dashboard migration.\n");
$audit = fopen($reportsDir . '/customer-tax-audit.csv', 'w');
fputcsv($audit, ['username', 'full_name', 'email', 'tax_id', 'plan', 'account_status']);
foreach ($seedUsers as $user) {
    fputcsv($audit, [$user[0], $user[2], $user[3], $user[11], $user[8], $user[9]]);
}
fclose($audit);

$db->commit();
chmod(__DIR__ . '/data', 0777);
chmod($reportsDir, 0777);

echo 'Seeded ' . count($seedUsers) . " Meridian CloudWorks user accounts\n";
?>
