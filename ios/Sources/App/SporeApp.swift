import SwiftUI
import SwiftData

@main
struct SporeApp: App {
    @Environment(\.scenePhase) private var scenePhase

    var sharedModelContainer: ModelContainer = AppGroup.makeSharedModelContainer()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .onChange(of: scenePhase) { _, newPhase in
                    if newPhase == .active {
                        let store = SwiftDataCaptureStore(modelContext: sharedModelContainer.mainContext)
                        let queue = CaptureQueue(store: store)
                        Task {
                            await queue.drain()
                        }
                    }
                }
                .onOpenURL { url in
                    DeepLink.handle(url)
                }
        }
        .modelContainer(sharedModelContainer)
    }
}
