import Foundation

/// Routes `spore://` URLs (widget taps, Control Center) to in-app
/// navigation. Story 2.5.
enum DeepLink {
    /// Posted with `selectedTab = .capture` when `spore://capture` is opened.
    static let openCaptureTab = Notification.Name("DeepLink.openCaptureTab")

    static func handle(_ url: URL) {
        guard url.scheme == "spore" else { return }
        if url.host == "capture" || url.path == "/capture" {
            NotificationCenter.default.post(name: openCaptureTab, object: nil)
        }
    }
}
