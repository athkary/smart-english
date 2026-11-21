import Foundation

/// Runtime configuration. Contains NO provider API keys — only the backend URL.
struct AppEnvironment: Sendable, Equatable {
    let apiBaseURL: URL
    let appVersion: String

    static func fromBundle(_ bundle: Bundle = .main) -> AppEnvironment {
        let raw = bundle.object(forInfoDictionaryKey: "API_BASE_URL") as? String
        let url = raw.flatMap(URL.init(string:)) ?? URL(string: "http://localhost:8000")!
        let version = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
        return AppEnvironment(apiBaseURL: url, appVersion: version)
    }
}

/// Compares dotted versions ("0.10.1" > "0.9.9").
enum VersionCompare {
    static func isAtLeast(_ version: String, minimum: String) -> Bool {
        let a = version.split(separator: ".").map { Int($0) ?? 0 }
        let b = minimum.split(separator: ".").map { Int($0) ?? 0 }
        for i in 0..<max(a.count, b.count) {
            let x = i < a.count ? a[i] : 0
            let y = i < b.count ? b[i] : 0
            if x != y { return x > y }
        }
        return true
    }
}
