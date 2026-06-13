import Foundation

/// Error surface for capture sync attempts.
enum CaptureAPIError: Error, Equatable {
    case notConfigured
    case server(status: Int)
    case transport(String)
}

/// Abstraction over the `/capture` endpoint so CaptureQueue can be tested
/// without any network access.
protocol CaptureAPI: Sendable {
    /// Posts a single capture. Returns once the backend has accepted it
    /// (HTTP 200 or 201). Throws on any other status or transport failure.
    func postCapture(captureUUID: UUID, body: String, source: String, deviceID: String?) async throws
}

/// Wire format for `POST /capture`.
private struct CapturePayload: Encodable {
    let captureUUID: UUID
    let source: String
    let body: String
    let deviceID: String?

    enum CodingKeys: String, CodingKey {
        case captureUUID = "capture_uuid"
        case source
        case body
        case deviceID = "device_id"
    }
}

/// Live implementation backed by `URLSession`, talking to the FastAPI
/// backend's `POST /capture` endpoint per CLAUDE.md's backend contract.
struct URLSessionCaptureAPI: CaptureAPI {
    let config: SporeConfig
    let session: URLSession

    init(config: SporeConfig = .shared, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    func postCapture(captureUUID: UUID, body: String, source: String, deviceID: String?) async throws {
        guard let baseURL = config.apiBaseURL else {
            throw CaptureAPIError.notConfigured
        }

        let url = baseURL.appendingPathComponent("capture")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(config.captureToken)", forHTTPHeaderField: "Authorization")

        let payload = CapturePayload(
            captureUUID: captureUUID,
            source: source,
            body: body,
            deviceID: deviceID
        )
        request.httpBody = try JSONEncoder().encode(payload)

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
