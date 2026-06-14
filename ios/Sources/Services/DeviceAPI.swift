import Foundation

/// Abstraction over `POST /devices` so `PushRegistrar` can be tested without
/// any network access.
protocol DeviceAPI: Sendable {
    /// Registers an APNs device token with the backend. `apnsToken` is the
    /// lowercase-hex-encoded device token.
    func registerDevice(apnsToken: String) async throws
}

/// Wire format for `POST /devices`.
private struct DeviceRegistrationPayload: Encodable {
    let apnsToken: String
    let platform: String

    enum CodingKeys: String, CodingKey {
        case apnsToken = "apns_token"
        case platform
    }
}

/// Live implementation backed by `URLSession`, talking to the FastAPI
/// backend's `POST /devices` endpoint (NFR5: no APNs/Anthropic keys in the
/// binary — only the capture token + device token are sent).
struct URLSessionDeviceAPI: DeviceAPI {
    let config: SporeConfig
    let session: URLSession

    init(config: SporeConfig = .shared, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    func registerDevice(apnsToken: String) async throws {
        guard let baseURL = config.apiBaseURL else {
            throw CaptureAPIError.notConfigured
        }

        let url = baseURL.appendingPathComponent("devices")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(config.captureToken)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONEncoder().encode(
            DeviceRegistrationPayload(apnsToken: apnsToken, platform: "ios")
        )

        let (_, response): (Data, URLResponse)
        do {
            (_, response) = try await session.data(for: request)
        } catch {
            throw CaptureAPIError.transport(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw CaptureAPIError.transport("non-HTTP response")
        }

        guard (200...299).contains(http.statusCode) else {
            throw CaptureAPIError.server(status: http.statusCode)
        }
    }
}
