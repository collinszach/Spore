import Foundation
import SwiftData

/// A locally-queued capture awaiting (or having completed) sync to the backend.
///
/// `id` doubles as the `capture_uuid` sent to `/capture` — this is what makes
/// retries idempotent on the backend.
@Model
final class CaptureQueueItem {
    var id: UUID
    var body: String
    var source: String
    var createdAt: Date
    var syncedAt: Date?
    var attemptCount: Int
    var lastError: String?

    init(
        id: UUID = UUID(),
        body: String,
        source: String,
        createdAt: Date = Date(),
        syncedAt: Date? = nil,
        attemptCount: Int = 0,
        lastError: String? = nil
    ) {
        self.id = id
        self.body = body
        self.source = source
        self.createdAt = createdAt
        self.syncedAt = syncedAt
        self.attemptCount = attemptCount
        self.lastError = lastError
    }

    var isSynced: Bool { syncedAt != nil }
}
