import Foundation
import Network

/// Observes network reachability and notifies on reconnect so CaptureQueue
/// can drain queued captures as soon as a path becomes available.
@Observable
final class NetworkMonitor {
    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "com.spore.app.network-monitor")

    private(set) var isConnected: Bool = true

    /// Called whenever the path transitions from unsatisfied to satisfied.
    var onReconnect: (() -> Void)?

    init() {
        monitor.pathUpdateHandler = { [weak self] path in
            guard let self else { return }
            let wasConnected = self.isConnected
            let nowConnected = path.status == .satisfied
            Task { @MainActor in
                self.isConnected = nowConnected
            }
            if !wasConnected && nowConnected {
                self.onReconnect?()
            }
        }
    }

    func start() {
        monitor.start(queue: queue)
    }

    func stop() {
        monitor.cancel()
    }
}
