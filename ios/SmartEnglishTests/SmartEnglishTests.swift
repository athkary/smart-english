import Foundation
import Testing
@testable import SmartEnglish

// MARK: - URLProtocol stub (no network in unit tests)

final class StubURLProtocol: URLProtocol {
    struct Stub: Sendable { let status: Int; let body: String }
    nonisolated(unsafe) static var stubs: [String: Stub] = [:]   // path -> response; tests run serialized
    nonisolated(unsafe) static var lastRequest: URLRequest?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lastRequest = request
        let path = request.url?.path ?? ""
        guard let stub = Self.stubs[path] else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost)); return
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: stub.status, httpVersion: nil,
                                       headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(stub.body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

private func makeClient() -> APIClient {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [StubURLProtocol.self]
    return APIClient(baseURL: URL(string: "http://test.local")!, session: URLSession(configuration: config))
}

private let metaJSON = """
{"app":"SMART ENGLISH AI","tagline_en":"Learn English. Speak with Confidence.","tagline_ar":"تعلّم الإنجليزية. تحدّث بثقة.",
 "api_version":"1","server_version":"0.1.0","min_ios_app_version":"0.1.0","supported_languages":["ar","en"],
 "levels":["A0","A1","A2"],
 "teachers":[{"code":"emma","display_name":"Emma","description_en":"Friendly teacher for beginners",
              "description_ar":"معلمة ودودة للمبتدئين","min_level":"A0","available":true}],
 "features":{"parent_accounts":false,"ai_teacher":false,"voice_classroom":false,"curriculum":false,
             "pronunciation_assessment":false,"games":false,"parent_dashboard":false,"subscriptions":false}}
"""

@Suite(.serialized)
struct APIClientTests {
    @Test func decodesMetaFromSnakeCase() async throws {
        StubURLProtocol.stubs = ["/v1/meta": .init(status: 200, body: metaJSON)]
        let meta = try await makeClient().meta()
        #expect(meta.teachers.first?.descriptionAr == "معلمة ودودة للمبتدئين")
        #expect(meta.features.voiceClassroom == false)
        #expect(StubURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Request-ID")?.count == 32)
    }

    @Test func mapsBilingualServerError() async {
        StubURLProtocol.stubs = ["/health": .init(status: 503, body:
            #"{"error":{"code":"feature_unavailable","message":"Down","message_ar":"غير متاح","request_id":"r1"}}"#)]
        do {
            _ = try await makeClient().health()
            Issue.record("expected error")
        } catch {
            #expect(error.message(arabic: true) == "غير متاح")
            if case .server(let status, _) = error { #expect(status == 503) } else { Issue.record("wrong case") }
        }
    }

    @Test func connectionFailureIsTransportError() async {
        StubURLProtocol.stubs = [:]
        do { _ = try await makeClient().health(); Issue.record("expected error") }
        catch { if case .transport = error {} else { Issue.record("got \(error)") } }
    }

    @MainActor @Test func appStateConnectsAndChecksVersion() async {
        StubURLProtocol.stubs = ["/health": .init(status: 200, body: #"{"status":"ok"}"#),
                                 "/v1/meta": .init(status: 200, body: metaJSON)]
        let ok = AppState(environment: .init(apiBaseURL: URL(string: "http://test.local")!, appVersion: "0.1.0"),
                          api: makeClient())
        await ok.refresh()
        #expect(ok.meta?.serverVersion == "0.1.0")

        let old = AppState(environment: .init(apiBaseURL: URL(string: "http://test.local")!, appVersion: "0.0.9"),
                           api: makeClient())
        await old.refresh()
        #expect(old.connection == .updateRequired(minimum: "0.1.0"))
    }
}

struct VersionCompareTests {
    @Test(arguments: [("0.1.0", "0.1.0", true), ("0.10.0", "0.9.9", true), ("0.1", "0.1.1", false), ("1.0.0", "0.99", true)])
    func compare(v: String, min: String, expected: Bool) {
        #expect(VersionCompare.isAtLeast(v, minimum: min) == expected)
    }
}

@MainActor
struct LanguageManagerTests {
    private func freshDefaults() -> UserDefaults {
        let name = "test.\(UUID().uuidString)"
        return UserDefaults(suiteName: name)!
    }

    @Test func defaultsToArabicRTLWithTranslations() {
        let m = LanguageManager(defaults: freshDefaults())
        #expect(m.language == .arabic)
        #expect(m.isRTL)
        #expect(m.showArabicTranslations)
        #expect(m.t("settings.title") == "الإعدادات")
    }

    @Test func switchingLanguagePersistsAndFlipsDirection() {
        let d = freshDefaults()
        let m = LanguageManager(defaults: d)
        m.setLanguage(.english)
        #expect(!m.isRTL)
        #expect(m.t("settings.title") == "Settings")
        m.showArabicTranslations = false
        let reloaded = LanguageManager(defaults: d)
        #expect(reloaded.language == .english)
        #expect(reloaded.showArabicTranslations == false)
    }

    @Test func unknownKeyFallsBackToKey() {
        #expect(LanguageManager(defaults: freshDefaults()).t("no.such.key") == "no.such.key")
    }
}
