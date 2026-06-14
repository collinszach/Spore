import Foundation

/// Abstraction over `POST /capture/audio` so `VoiceCaptureViewModel` can be
/// tested without any network access (Story 2.6).
protocol AudioCaptureAPI: Sendable {
    /// Uploads a recorded audio file. Returns once the backend has accepted
    /// it (HTTP 200 or 201, per the `/capture/audio` idempotent-retry
    /// contract). Throws on any other status or transport failure.
    func sendAudio(captureUUID: UUID, fileURL: URL, source: String) async throws
}

/// Live implementation backed by `URLSession`, doing a multipart/form-data
/// POST to the FastAPI backend's `/capture/audio` endpoint per CLAUDE.md's
/// backend contract.
struct URLSessionAudioCaptureAPI: AudioCaptureAPI {
    let config: SporeConfig
    let session: URLSession

    init(config: SporeConfig = .shared, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    func sendAudio(captureUUID: UUID, fileURL: URL, source: String) async throws {
        guard let baseURL = config.apiBaseURL else {
            throw CaptureAPIError.notConfigured
        }

        let url = baseURL.appendingPathComponent("capture/audio")
        let boundary = "Boundary-\(UUID().uuidString)"

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(config.captureToken)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        let audioData: Data
        do {
            audioData = try Data(contentsOf: fileURL)
        } catch {
            throw CaptureAPIError.transport(error.localizedDescription)
        }

        var body = Data()
        appendFormField(&body, boundary: boundary, name: "capture_uuid", value: captureUUID.uuidString)
        appendFormField(&body, boundary: boundary, name: "source", value: source)
        appendFormFile(
            &body,
            boundary: boundary,
            name: "audio",
            filename: fileURL.lastPathComponent,
            mimeType: "audio/m4a",
            fileData: audioData
        )
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

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

    private func appendFormField(_ body: inout Data, boundary: String, name: String, value: String) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(value)\r\n".data(using: .utf8)!)
    }

    private func appendFormFile(_ body: inout Data, boundary: String, name: String, filename: String, mimeType: String, fileData: Data) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n".data(using: .utf8)!)
    }
}
