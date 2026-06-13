import Foundation
import SwiftData

/// App Group identifier shared by the main app, Share Extension, and Widget
/// extension so they can all enqueue into ONE offline capture queue
/// (Story 2.3/2.4/2.5).
enum AppGroup {
    static let identifier = "group.com.spore.app"

    /// Shared container URL for the App Group, used to locate the SwiftData
    /// store so all targets read/write the same `CaptureQueueItem` database.
    static var containerURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: identifier)
    }

    /// Shared `UserDefaults` for the App Group, used to distribute
    /// `SPORE_API_BASE_URL` / `SPORE_CAPTURE_TOKEN` to extensions (NFR5: no
    /// secrets hardcoded in extension targets).
    static var defaults: UserDefaults? {
        UserDefaults(suiteName: identifier)
    }

    /// Builds the shared `ModelContainer` used by the app and extensions.
    /// Falls back to the default (non-shared) container location if the App
    /// Group container is unavailable (e.g. running in a test host without
    /// entitlements), so previews/tests never crash.
    static func makeSharedModelContainer() -> ModelContainer {
        let schema = Schema([CaptureQueueItem.self])

        if let containerURL {
            let storeURL = containerURL.appendingPathComponent("Spore.sqlite")
            let configuration = ModelConfiguration(schema: schema, url: storeURL)
            if let container = try? ModelContainer(for: schema, configurations: [configuration]) {
                return container
            }
        }

        // Fallback: default app-local store (e.g. App Group entitlement not
        // present in this build environment).
        let fallbackConfiguration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: false)
        return try! ModelContainer(for: schema, configurations: [fallbackConfiguration])
    }
}
