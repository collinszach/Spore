import WidgetKit
import SwiftUI
import AppIntents

/// Control Center control for one-tap capture (Story 2.5 / FR4, iOS 18+).
/// Tapping it opens the app via `spore://capture` so the user lands on the
/// Capture tab with the keyboard focused.
@available(iOS 18.0, *)
struct SporeCaptureControl: ControlWidget {
    static let kind: String = "com.zacharyjcollins.spore.capture-control"

    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: Self.kind) {
            ControlWidgetButton(action: OpenURLIntent(URL(string: "spore://capture")!)) {
                Label("New Thought", systemImage: "square.and.pencil")
            }
        }
        .displayName("Spore Capture")
        .description("Quickly open Spore to capture a thought.")
    }
}
