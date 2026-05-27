<?php
function db() {
    $db = new PDO(database_dsn(), database_user(), database_password(), [
        PDO::ATTR_TIMEOUT => 5,
    ]);
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    initialize_db($db);
    return $db;
}

function database_dsn() {
    $host = getenv('SAAS_DB_HOST') ?: 'mysql';
    $port = getenv('SAAS_DB_PORT') ?: '3306';
    $name = getenv('SAAS_DB_NAME') ?: 'app';
    return 'mysql:host=' . $host . ';port=' . $port . ';dbname=' . $name . ';charset=utf8mb4';
}

function database_user() {
    return getenv('SAAS_DB_USER') ?: 'app_user';
}

function database_password() {
    return getenv('SAAS_DB_PASSWORD') ?: 'app_password';
}

function database_description() {
    $host = getenv('SAAS_DB_HOST') ?: 'mysql';
    $port = getenv('SAAS_DB_PORT') ?: '3306';
    $name = getenv('SAAS_DB_NAME') ?: 'app';
    return 'mysql://' . $host . ':' . $port . '/' . $name;
}

function data_path($name) {
    return __DIR__ . '/data/' . basename($name);
}

function initialize_db($db) {
    $db->exec('CREATE TABLE IF NOT EXISTS users (
        id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(191) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        full_name VARCHAR(255) NOT NULL,
        email VARCHAR(255) NOT NULL,
        phone VARCHAR(64),
        department VARCHAR(128) NOT NULL,
        title VARCHAR(255) NOT NULL,
        region VARCHAR(64) NOT NULL,
        plan VARCHAR(64) NOT NULL,
        account_status VARCHAR(64) NOT NULL DEFAULT "active",
        last_login_at VARCHAR(64),
        ssn VARCHAR(64),
        role VARCHAR(64) NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS login_attempts (
        id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        attempted_at VARCHAR(64) NOT NULL,
        username VARCHAR(191),
        remote_addr VARCHAR(64),
        successful TINYINT(1) NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS account_notes (
        id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        user_id INT UNSIGNED NOT NULL,
        note TEXT NOT NULL,
        created_at VARCHAR(64) NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS api_keys (
        id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        owner_username VARCHAR(191) NOT NULL,
        service VARCHAR(191) NOT NULL,
        token TEXT NOT NULL,
        scope VARCHAR(255) NOT NULL,
        created_at VARCHAR(64) NOT NULL
    )');
}

function fragile_startup_delay_s() {
    $configured = getenv('SAAS_STARTUP_DELAY_S');
    if ($configured === false || $configured === '') {
        return 0;
    }
    return max(0, intval($configured));
}

function startup_ready() {
    $path = data_path('started_at');
    if (!file_exists($path)) {
        file_put_contents($path, strval(time()));
    }
    return time() - intval(trim(file_get_contents($path))) >= fragile_startup_delay_s();
}

function record_login_attempt($db, $username, $successful) {
    $stmt = $db->prepare('INSERT INTO login_attempts (attempted_at, username, remote_addr, successful) VALUES (?, ?, ?, ?)');
    $stmt->execute([date('c'), $username, $_SERVER['REMOTE_ADDR'] ?? '', $successful ? 1 : 0]);
}

function failed_login_count($db) {
    $window = failed_login_window_s();
    if ($window <= 0) {
        return intval($db->query('SELECT COUNT(*) FROM login_attempts WHERE successful = 0')->fetchColumn());
    }
    $cutoff = date('c', time() - $window);
    $stmt = $db->prepare('SELECT COUNT(*) FROM login_attempts WHERE successful = 0 AND attempted_at >= ?');
    $stmt->execute([$cutoff]);
    return intval($stmt->fetchColumn());
}

function outage_file() {
    return '/tmp/acme_saas_maintenance.lock';
}

function failed_login_outage_threshold() {
    $configured = getenv('SAAS_FAILED_LOGIN_OUTAGE_THRESHOLD');
    if ($configured === false || $configured === '') {
        return 4;
    }
    return max(1, intval($configured));
}

function failed_login_window_s() {
    $configured = getenv('SAAS_FAILED_LOGIN_WINDOW_S');
    if ($configured === false || $configured === '') {
        return 60;
    }
    return max(0, intval($configured));
}

function outage_lock_ttl_s() {
    $configured = getenv('SAAS_OUTAGE_LOCK_TTL_S');
    if ($configured === false || $configured === '') {
        return 600;
    }
    return max(0, intval($configured));
}

function outage_active($db) {
    $path = outage_file();
    if (!file_exists($path)) {
        return false;
    }
    $ttl = outage_lock_ttl_s();
    if ($ttl > 0 && time() - filemtime($path) >= $ttl) {
        unlink($path);
        return false;
    }
    return true;
}

function set_outage($enabled) {
    if ($enabled) {
        file_put_contents(outage_file(), "login protection triggered maintenance mode\n");
    } elseif (file_exists(outage_file())) {
        unlink(outage_file());
    }
}

function require_app_available($db) {
    if (!startup_ready()) {
        http_response_code(503);
        echo "Application is starting. Please retry shortly.";
        exit;
    }
    if (outage_active($db)) {
        http_response_code(503);
        echo "Service temporarily unavailable.";
        exit;
    }
}
?>
