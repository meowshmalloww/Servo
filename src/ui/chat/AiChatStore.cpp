#include "AiChatStore.h"

#include <QDateTime>
#include <QDir>
#include <QSqlQuery>
#include <QStandardPaths>
#include <QUuid>

namespace {
constexpr qint64 CacheLifetimeSeconds = 30LL * 24 * 60 * 60;
constexpr int MaximumCacheEntries = 250;
}

AiChatStore::AiChatStore(const QString &databasePath)
    : m_connectionName(QStringLiteral("servo-ai-chat-%1").arg(QUuid::createUuid().toString(QUuid::Id128)))
{
    if (databasePath.isEmpty()) {
        const QString dataDirectory = QStandardPaths::writableLocation(
            QStandardPaths::AppLocalDataLocation);
        if (!QDir().mkpath(dataDirectory))
            return;
        m_databasePath = QDir(dataDirectory).filePath(QStringLiteral("ai-chat.sqlite3"));
    } else {
        m_databasePath = databasePath;
    }

    m_database = QSqlDatabase::addDatabase(QStringLiteral("QSQLITE"), m_connectionName);
    m_database.setDatabaseName(m_databasePath);
    m_database.setConnectOptions(QStringLiteral("QSQLITE_BUSY_TIMEOUT=3000"));
    if (!m_database.open())
        return;

    initialize();
    pruneCache();
}

AiChatStore::~AiChatStore()
{
    if (m_database.isValid())
        m_database.close();
    m_database = {};
    QSqlDatabase::removeDatabase(m_connectionName);
}

bool AiChatStore::isOpen() const
{
    return m_database.isOpen();
}

QString AiChatStore::databasePath() const
{
    return m_databasePath;
}

std::optional<QString> AiChatStore::cachedResponse(const QString &cacheKey)
{
    if (!isOpen() || cacheKey.isEmpty())
        return std::nullopt;

    QSqlQuery query(m_database);
    query.prepare(QStringLiteral(
        "SELECT response FROM response_cache WHERE cache_key = ? LIMIT 1"));
    query.addBindValue(cacheKey);
    if (!query.exec() || !query.next())
        return std::nullopt;

    const QString response = query.value(0).toString();
    QSqlQuery touch(m_database);
    touch.prepare(QStringLiteral(
        "UPDATE response_cache SET last_used_at = ? WHERE cache_key = ?"));
    touch.addBindValue(QDateTime::currentSecsSinceEpoch());
    touch.addBindValue(cacheKey);
    touch.exec();
    return response;
}

void AiChatStore::storeResponse(const QString &cacheKey, const QString &response)
{
    if (!isOpen() || cacheKey.isEmpty() || response.isEmpty())
        return;

    const qint64 now = QDateTime::currentSecsSinceEpoch();
    QSqlQuery query(m_database);
    query.prepare(QStringLiteral(
        "INSERT INTO response_cache(cache_key, response, created_at, last_used_at) "
        "VALUES(?, ?, ?, ?) "
        "ON CONFLICT(cache_key) DO UPDATE SET response = excluded.response, "
        "last_used_at = excluded.last_used_at"));
    query.addBindValue(cacheKey);
    query.addBindValue(response);
    query.addBindValue(now);
    query.addBindValue(now);
    query.exec();
    pruneCache();
}

std::optional<AiChatStore::PendingJob> AiChatStore::pendingJob() const
{
    if (!isOpen())
        return std::nullopt;

    QSqlQuery query(m_database);
    if (!query.exec(QStringLiteral(
            "SELECT name, prompt, cache_key, model_name FROM pending_jobs "
            "ORDER BY created_at DESC LIMIT 1"))
        || !query.next()) {
        return std::nullopt;
    }

    return PendingJob{
        query.value(0).toString(),
        query.value(1).toString(),
        query.value(2).toString(),
        query.value(3).toString(),
    };
}

void AiChatStore::storePendingJob(const PendingJob &job)
{
    if (!isOpen() || job.name.isEmpty())
        return;

    QSqlQuery query(m_database);
    query.prepare(QStringLiteral(
        "INSERT OR REPLACE INTO pending_jobs(name, prompt, cache_key, model_name, created_at) "
        "VALUES(?, ?, ?, ?, ?)"));
    query.addBindValue(job.name);
    query.addBindValue(job.prompt);
    query.addBindValue(job.cacheKey);
    query.addBindValue(job.modelName);
    query.addBindValue(QDateTime::currentSecsSinceEpoch());
    query.exec();
}

void AiChatStore::removePendingJob(const QString &name)
{
    if (!isOpen() || name.isEmpty())
        return;

    QSqlQuery query(m_database);
    query.prepare(QStringLiteral("DELETE FROM pending_jobs WHERE name = ?"));
    query.addBindValue(name);
    query.exec();
}

void AiChatStore::initialize()
{
    QSqlQuery query(m_database);
    query.exec(QStringLiteral(
        "CREATE TABLE IF NOT EXISTS response_cache("
        "cache_key TEXT PRIMARY KEY, response TEXT NOT NULL, "
        "created_at INTEGER NOT NULL, last_used_at INTEGER NOT NULL)"));
    query.exec(QStringLiteral(
        "CREATE TABLE IF NOT EXISTS pending_jobs("
        "name TEXT PRIMARY KEY, prompt TEXT NOT NULL, cache_key TEXT NOT NULL, "
        "model_name TEXT NOT NULL, created_at INTEGER NOT NULL)"));
}

void AiChatStore::pruneCache()
{
    if (!isOpen())
        return;

    QSqlQuery query(m_database);
    query.prepare(QStringLiteral("DELETE FROM response_cache WHERE created_at < ?"));
    query.addBindValue(QDateTime::currentSecsSinceEpoch() - CacheLifetimeSeconds);
    query.exec();
    query.exec(QStringLiteral(
        "DELETE FROM response_cache WHERE cache_key NOT IN ("
        "SELECT cache_key FROM response_cache ORDER BY last_used_at DESC LIMIT %1)"
    ).arg(MaximumCacheEntries));
}
