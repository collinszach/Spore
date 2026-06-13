import Foundation

/// Shared "coming soon" ViewModel for screens that aren't built yet
/// (Review, Pipeline, Notes, Today). Each tab gets its own instance so
/// later stories can replace the implementation without touching the
/// tab scaffolding.
@MainActor
@Observable
final class PlaceholderViewModel {
    let title: String
    let subtitle: String
    let systemImage: String

    init(title: String, subtitle: String, systemImage: String) {
        self.title = title
        self.subtitle = subtitle
        self.systemImage = systemImage
    }
}
