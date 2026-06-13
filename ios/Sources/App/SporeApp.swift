import SwiftUI
import SwiftData

@main
struct SporeApp: App {
    @Environment(\.scenePhase) private var scenePhase

    var sharedModelContainer: ModelContainer = {
        let schema = Schema([CaptureQueueItem.self])
        let configuration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: false)
        return try! ModelContainer(for: schema, configurations: [configuration])
    }()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .onChange(of: scenePhase) { _, newPhase in
                    if newPhase == .active {
                        let queue = CaptureQueue(modelContext: sharedModelContainer.mainContext)
                        Task {
                            await queue.drain()
                        }
                    }
                }
        }
        .modelContainer(sharedModelContainer)
    }
}
