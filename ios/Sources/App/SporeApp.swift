import SwiftUI
import SwiftData
import UIKit
import UserNotifications

/// Requests notification authorization on launch and forwards the resulting
/// APNs device token to the backend via `PushRegistrar` (Story: APNs push
/// registration). Push capability is a no-op on the simulator but must still
/// compile and not crash.
final class AppDelegate: NSObject, UIApplicationDelegate {
    let pushRegistrar = PushRegistrar()

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        Task {
            let center = UNUserNotificationCenter.current()
            do {
                let granted = try await center.requestAuthorization(options: [.alert, .sound, .badge])
                if granted {
                    await MainActor.run {
                        application.registerForRemoteNotifications()
                    }
                }
            } catch {
                #if DEBUG
                print("AppDelegate: notification authorization request failed: \(error)")
                #endif
            }
        }
        return true
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        Task {
            await pushRegistrar.register(deviceToken: deviceToken)
        }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        #if DEBUG
        print("AppDelegate: failed to register for remote notifications: \(error)")
        #endif
    }
}

@main
struct SporeApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

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
