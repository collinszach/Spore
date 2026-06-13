import Foundation

/// Error surface for Review/Pipeline API calls.
enum SporeAPIError: Error, Equatable {
    case notConfigured
    case server(status: Int)
    case api(String)
    case transport(String)
    case decoding(String)
}

/// Generic `{ok, data, error}` envelope used by every Spore backend endpoint.
private struct Envelope<T: Decodable>: Decodable {
    let ok: Bool
    let data: T?
    let error: EnvelopeError?
}

/// `error` may be a plain string or a structured object (e.g. pipeline move
/// 409s). We only need a human-readable message on the client.
private enum EnvelopeError: Decodable {
    case message(String)
    case structured([String: AnyDecodable])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let string = try? container.decode(String.self) {
            self = .message(string)
        } else if let dict = try? container.decode([String: AnyDecodable].self) {
            self = .structured(dict)
        } else {
            self = .message("unknown error")
        }
    }

    var description: String {
        switch self {
        case .message(let string):
            return string
        case .structured(let dict):
            if case .string(let message)? = dict["message"]?.value as? AnyDecodable.Value {
                return message
            }
            return "request failed"
        }
    }
}

/// Minimal type-erased decodable used only to absorb structured error bodies.
private struct AnyDecodable: Decodable {
    enum Value {
        case string(String)
        case other
    }
    let value: Any

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let string = try? container.decode(String.self) {
            value = Value.string(string)
        } else {
            value = Value.other
        }
    }
}

/// Decodes ISO8601 timestamps from `pydantic`'s `model_dump(mode="json")`,
/// which may or may not include fractional seconds.
private func decodeFlexibleISO8601(_ decoder: Decoder) throws -> Date {
    let container = try decoder.singleValueContainer()
    let string = try container.decode(String.self)

    let withFractional = ISO8601DateFormatter()
    withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = withFractional.date(from: string) {
        return date
    }

    let withoutFractional = ISO8601DateFormatter()
    withoutFractional.formatOptions = [.withInternetDateTime]
    if let date = withoutFractional.date(from: string) {
        return date
    }

    throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid ISO8601 date: \(string)")
}

// MARK: - DTOs (mirror backend/app/schemas.py)

/// Mirrors `ReviewItemOut`.
struct ReviewItemDTO: Codable, Identifiable, Equatable {
    let id: UUID
    let captureID: UUID?
    let reason: String?
    let status: String
    let suggestedPath: String?
    let suggestedType: String?
    let confidence: Double?
    let createdAt: Date
    let resolvedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case captureID = "capture_id"
        case reason
        case status
        case suggestedPath = "suggested_path"
        case suggestedType = "suggested_type"
        case confidence
        case createdAt = "created_at"
        case resolvedAt = "resolved_at"
    }
}

/// Review actions, mirroring `VALID_ACTIONS` in `app.services.review_service`.
enum ReviewAction: String {
    case approve
    case redirect
    case merge
    case discard
}

/// Mirrors `RedirectIn` — all fields optional, only changed ones sent.
struct RedirectPayload: Encodable {
    var type: String?
    var domain: String?
    var tags: [String]?
    var suggestedPath: String?

    enum CodingKeys: String, CodingKey {
        case type
        case domain
        case tags
        case suggestedPath = "suggested_path"
    }
}

/// Mirrors `MergeIn`.
struct MergePayload: Encodable {
    let targetNoteID: UUID

    enum CodingKeys: String, CodingKey {
        case targetNoteID = "target_note_id"
    }
}

/// Mirrors `PipelineNoteOut`.
struct PipelineNoteDTO: Codable, Identifiable, Equatable {
    let id: UUID
    let title: String?
    let type: String?
    let ideaState: String?
    let domain: String?
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case type
        case ideaState = "idea_state"
        case domain
        case updatedAt = "updated_at"
    }
}

/// Mirrors the `GET /pipeline` response `data` shape:
/// `{"states": {state: [PipelineNoteOut]}, "counts": {state: int}}`.
struct PipelineDTO: Decodable, Equatable {
    let states: [String: [PipelineNoteDTO]]
    let counts: [String: Int]
}

/// Mirrors `PipelineMoveIn`.
private struct PipelineMovePayload: Encodable {
    let toState: String

    enum CodingKeys: String, CodingKey {
        case toState = "to_state"
    }
}

// MARK: - Protocol

/// Abstraction over the `/review` and `/pipeline` endpoints so view models
/// can be tested without any network access.
protocol SporeAPI: Sendable {
    func fetchReviewQueue() async throws -> [ReviewItemDTO]
    func act(reviewID: UUID, action: ReviewAction, redirect: RedirectPayload?, merge: MergePayload?) async throws -> ReviewItemDTO
    func fetchPipeline() async throws -> PipelineDTO
    func moveNote(id: UUID, to state: String) async throws -> PipelineNoteDTO
}

extension SporeAPI {
    /// Convenience for actions with no body (approve/discard).
    func act(reviewID: UUID, action: ReviewAction) async throws -> ReviewItemDTO {
        try await act(reviewID: reviewID, action: action, redirect: nil, merge: nil)
    }
}

// MARK: - Live implementation

/// Live implementation backed by `URLSession`, talking to the FastAPI
/// backend's `/review` and `/pipeline` endpoints per CLAUDE.md's contract.
struct URLSessionSporeAPI: SporeAPI {
    let config: SporeConfig
    let session: URLSession

    init(config: SporeConfig = .shared, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    func fetchReviewQueue() async throws -> [ReviewItemDTO] {
        var request = try makeRequest(path: "review", queryItems: [URLQueryItem(name: "status", value: "open")])
        request.httpMethod = "GET"
        return try await send(request)
    }

    func act(reviewID: UUID, action: ReviewAction, redirect: RedirectPayload?, merge: MergePayload?) async throws -> ReviewItemDTO {
        var request = try makeRequest(path: "review/\(reviewID.uuidString)/\(action.rawValue)")
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        switch action {
        case .redirect:
            request.httpBody = try JSONEncoder().encode(redirect ?? RedirectPayload())
        case .merge:
            guard let merge else {
                throw SporeAPIError.api("merge requires a target_note_id")
            }
            request.httpBody = try JSONEncoder().encode(merge)
        case .approve, .discard:
            break
        }

        return try await send(request)
    }

    func fetchPipeline() async throws -> PipelineDTO {
        var request = try makeRequest(path: "pipeline")
        request.httpMethod = "GET"
        return try await send(request)
    }

    func moveNote(id: UUID, to state: String) async throws -> PipelineNoteDTO {
        var request = try makeRequest(path: "pipeline/\(id.uuidString)/move")
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(PipelineMovePayload(toState: state))
        return try await send(request)
    }

    // MARK: - Helpers

    private func makeRequest(path: String, queryItems: [URLQueryItem]? = nil) throws -> URLRequest {
        guard let baseURL = config.apiBaseURL else {
            throw SporeAPIError.notConfigured
        }

        var url = baseURL.appendingPathComponent(path)
        if let queryItems, !queryItems.isEmpty {
            guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
                throw SporeAPIError.transport("invalid URL")
            }
            components.queryItems = queryItems
            guard let composed = components.url else {
                throw SporeAPIError.transport("invalid URL")
            }
            url = composed
        }

        var request = URLRequest(url: url)
        request.setValue("Bearer \(config.captureToken)", forHTTPHeaderField: "Authorization")
        return request
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw SporeAPIError.transport(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw SporeAPIError.transport("non-HTTP response")
        }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom(decodeFlexibleISO8601)

        guard (200...299).contains(http.statusCode) else {
            if let envelope = try? decoder.decode(Envelope<T>.self, from: data), let error = envelope.error {
                throw SporeAPIError.api(error.description)
            }
            throw SporeAPIError.server(status: http.statusCode)
        }

        let envelope: Envelope<T>
        do {
            envelope = try decoder.decode(Envelope<T>.self, from: data)
        } catch {
            throw SporeAPIError.decoding(error.localizedDescription)
        }

        guard envelope.ok, let value = envelope.data else {
            throw SporeAPIError.api(envelope.error?.description ?? "request failed")
        }

        return value
    }
}
