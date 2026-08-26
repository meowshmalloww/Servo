#pragma once

#include <QSqlDatabase>
#include <QString>

#include <optional>

class AiChatStore final
{
public:
    struct PendingJob {
        QString name;
        QString prompt;
        QString cacheKey;
        QString modelName;
    };

    explicit AiChatStore(const QString &databasePath = {});
    ~AiChatStore();

    AiChatStore(const AiChatStore &) = delete;
    AiChatStore &operator=(const AiChatStore &) = delete;

    bool isOpen() const;
    QString databasePath() const;

    std::optional<QString> cachedResponse(const QString &cacheKey);
    void storeResponse(const QString &cacheKey, const QString &response);

    std::optional<PendingJob> pendingJob() const;
    void storePendingJob(const PendingJob &job);
    void removePendingJob(const QString &name);

private:
    void initialize();
    void pruneCache();

    QString m_connectionName;
    QString m_databasePath;
    QSqlDatabase m_database;
};
