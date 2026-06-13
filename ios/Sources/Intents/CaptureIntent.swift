import AppIntents
import Foundation

/// "Note to Spore" — Siri/Shortcuts entry point for capturing a thought
/// without opening the app (Story 2.4 / FR3).
struct CaptureIntent: AppIntent {
    static var title: LocalizedStringResource = "Note to Spore"
    static var description = IntentDescription("Quickly capture a thought to Spore's inbox.")

    /// Run in the foreground so the capture lands instantly without
    /// requiring app launch animation; SwiftData write is fast (<500ms).
    static var openAppWhenRun: Bool = false

    @Parameter(title: "Thought", requestValueDialog: "What's on your mind?")
    var text: String

    /// Injection seam for tests — defaults to the shared App Group store in
    /// production.
    @MainActor
    static var serviceProvider: () -> CaptureService = { CaptureService.shared() }

    init() {}

    init(text: String) {
        self.text = text
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let service = Self.serviceProvider()
        guard service.enqueue(body: text, source: "siri") != nil else {
            return .result(dialog: "I didn't catch anything to save.")
        }
        return .result(dialog: "Saved to Spore.")
    }
}

/// Exposes `CaptureIntent` to Siri and the Shortcuts app (Story 2.4).
struct SporeShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: CaptureIntent(),
            phrases: [
                "Note to \(.applicationName)",
                "Add a thought to \(.applicationName)",
                "Capture in \(.applicationName)"
            ],
            shortTitle: "Note to Spore",
            systemImageName: "square.and.pencil"
        )
    }
}
