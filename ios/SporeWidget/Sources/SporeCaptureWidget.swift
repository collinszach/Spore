import WidgetKit
import SwiftUI
import AppIntents

/// Static timeline entry — the widget has no dynamic state, it's purely a
/// quick-capture launcher.
struct CaptureEntry: TimelineEntry {
    let date: Date
}

struct CaptureWidgetProvider: TimelineProvider {
    func placeholder(in context: Context) -> CaptureEntry {
        CaptureEntry(date: Date())
    }

    func getSnapshot(in context: Context, completion: @escaping (CaptureEntry) -> Void) {
        completion(CaptureEntry(date: Date()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<CaptureEntry>) -> Void) {
        completion(Timeline(entries: [CaptureEntry(date: Date())], policy: .never))
    }
}

/// Home/Lock Screen widget for one-tap capture (Story 2.5 / FR4).
///
/// Tapping the widget body deep-links to `spore://capture` (opens the app
/// focused on the Capture tab). The "Quick note" button uses an iOS 17
/// interactive `Button(intent:)` to run `CaptureIntent` with an empty
/// prompt — Siri/Shortcuts UI then asks for the dictated text without fully
/// launching the app.
struct SporeCaptureWidget: Widget {
    let kind: String = "SporeCaptureWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: CaptureWidgetProvider()) { _ in
            SporeCaptureWidgetView()
        }
        .configurationDisplayName("Quick Capture")
        .description("Tap to jump straight into capturing a thought in Spore.")
        .supportedFamilies([.systemSmall, .accessoryCircular, .accessoryRectangular])
    }
}

struct SporeCaptureWidgetView: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        switch family {
        case .accessoryCircular:
            Link(destination: URL(string: "spore://capture")!) {
                Image(systemName: "square.and.pencil")
            }
        case .accessoryRectangular:
            Link(destination: URL(string: "spore://capture")!) {
                HStack {
                    Image(systemName: "square.and.pencil")
                    Text("New thought")
                }
            }
        default:
            Link(destination: URL(string: "spore://capture")!) {
                VStack(alignment: .leading, spacing: 8) {
                    Image(systemName: "square.and.pencil")
                        .font(.title2)
                    Text("Capture")
                        .font(.headline)
                    Text("Tap to add a thought")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding()
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            }
        }
    }
}
