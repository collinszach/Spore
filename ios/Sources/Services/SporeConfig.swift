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

    /// Reads config from the App Group's shared `UserDefaults` first (so
    /// extensions get the same `SPORE_API_BASE_URL`/`SPORE_CAPTURE_TOKEN` as
    /// the main app), falling back to the bundle's Info.plist.
    init(bundle: Bundle) {
        let sharedDefaults = AppGroup.defaults
        let sharedURL = sharedDefaults?.string(forKey: "SPORE_API_BASE_URL") ?? ""
        let sharedToken = sharedDefaults?.string(forKey: "SPORE_CAPTURE_TOKEN") ?? ""

        let plistURL = (bundle.object(forInfoDictionaryKey: "SPORE_API_BASE_URL") as? String) ?? ""
        let plistToken = (bundle.object(forInfoDictionaryKey: "SPORE_CAPTURE_TOKEN") as? String) ?? ""

        let rawURL = sharedURL.isEmpty ? plistURL : sharedURL
        let rawToken = sharedToken.isEmpty ? plistToken : sharedToken

        self.apiBaseURL = rawURL.isEmpty ? nil : URL(string: rawURL)
        self.captureToken = rawToken
    }

    init(apiBaseURL: URL?, captureToken: String) {
        self.apiBaseURL = apiBaseURL
        self.captureToken = captureToken
    }
}
