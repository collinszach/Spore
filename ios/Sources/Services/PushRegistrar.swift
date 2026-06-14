import Foundation

/// Converts an APNs device token (`Data`) to the backend's expected
/// lowercase-hex string and registers it via `DeviceAPI`.
///
/// Kept as a small, independently-testable type so `SporeApp`'s
/// `AppDelegate` can stay thin — no real APNs/network needed in tests.
struct PushRegistrar: Sendable {
    let api: DeviceAPI

    init(api: DeviceAPI = URLSessionDeviceAPI()) {
        self.api = api
    }

    /// Hex-encodes `deviceToken` and posts it to `/devices`. Failures are
    /// swallowed (logged) since push registration is best-effort and must
    /// never crash or block app launch.
    func register(deviceToken: Data) async {
        let hex = Self.hexString(from: deviceToken)
        do {
            try await api.registerDevice(apnsToken: hex)
        } catch {
            #if DEBUG
            print("PushRegistrar: failed to register device token: \(error)")
            #endif
        }
    }

    /// Lowercase-hex encoding of `data`, e.g. `Data([0x00, 0xFC])` -> `"00fc"`.
    static func hexString(from data: Data) -> String {
        data.map { String(format: "%02x", $0) }.joined()
    }
}
