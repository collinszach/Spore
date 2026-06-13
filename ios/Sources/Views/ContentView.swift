import SwiftUI
import SwiftData

/// App shell — five tabs, Capture selected by default (Story 2.1).
struct ContentView: View {
    @Environment(\.modelContext) private var modelContext
    @State private var selectedTab: Tab = .capture
    @State private var networkMonitor = NetworkMonitor()

    enum Tab: Hashable {
        case capture, review, pipeline, notes, today
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            CaptureView(viewModel: makeCaptureViewModel())
                .tabItem { Label("Capture", systemImage: "square.and.pencil") }
                .tag(Tab.capture)

            ReviewView(viewModel: ReviewViewModel(api: URLSessionSporeAPI()))
                .tabItem { Label("Review", systemImage: "checkmark.circle") }
                .tag(Tab.review)

            PipelineView(viewModel: PipelineViewModel(api: URLSessionSporeAPI()))
                .tabItem { Label("Pipeline", systemImage: "arrow.triangle.2.circlepath") }
                .tag(Tab.pipeline)

            PlaceholderView(viewModel: PlaceholderViewModel(
                title: "Notes",
                subtitle: "Coming soon — browse your Obsidian vault notes.",
                systemImage: "note.text"
            ))
            .tabItem { Label("Notes", systemImage: "note.text") }
            .tag(Tab.notes)

            PlaceholderView(viewModel: PlaceholderViewModel(
                title: "Today",
                subtitle: "Coming soon — your daily digest and reminders.",
                systemImage: "sun.max"
            ))
            .tabItem { Label("Today", systemImage: "sun.max") }
            .tag(Tab.today)
        }
        .onAppear {
            networkMonitor.onReconnect = {
                Task { @MainActor in
                    await makeCaptureViewModel().drainQueue()
                }
            }
            networkMonitor.start()
        }
        .onReceive(NotificationCenter.default.publisher(for: DeepLink.openCaptureTab)) { _ in
            selectedTab = .capture
        }
    }

    private func makeCaptureViewModel() -> CaptureViewModel {
        let store = SwiftDataCaptureStore(modelContext: modelContext)
        return CaptureViewModel(queue: CaptureQueue(store: store))
    }
}

#Preview {
    ContentView()
        .modelContainer(PreviewSupport.container)
}
