import Foundation

/// Runtime configuration read from Info.plist.
///
/// NFR5: no Claude/API keys live in the binary. The only secret here is a
/// capture device token used to authenticate against the Spore backend's
/// `/capture` endpoint — never an Anthropic key.
struct SporeConfig {
    let apiBaseURL: URL?
    let captureToken: String

    static let shared = SporeConfig(bundle: .main)

    init(bundle: Bundle) {
        let rawURL = (bundle.object(forInfoDictionaryKey: "SPORE_API_BASE_URL") as? String) ?? ""
        let rawToken = (bundle.object(forInfoDictionaryKey: "SPORE_CAPTURE_TOKEN") as? String) ?? ""

        self.apiBaseURL = rawURL.isEmpty ? nil : URL(string: rawURL)
        self.captureToken = rawToken
    }

    init(apiBaseURL: URL?, captureToken: String) {
        self.apiBaseURL = apiBaseURL
        self.captureToken = captureToken
    }
}
