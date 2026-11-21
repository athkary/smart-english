import Foundation

// MARK: - Models (mirror backend/app/modules/meta/catalog.py)

struct TeacherInfo: Codable, Sendable, Identifiable, Equatable {
    let code: String
    let displayName: String
    let descriptionEn: String
    let descriptionAr: String
    let minLevel: String
    let available: Bool
    var id: String { code }
}

struct FeatureFlags: Codable, Sendable, Equatable {
    let parentAccounts: Bool
    let aiTeacher: Bool
    let voiceClassroom: Bool
    let curriculum: Bool
    let pronunciationAssessment: Bool
    let games: Bool
    let parentDashboard: Bool
    let subscriptions: Bool
}

struct MetaResponse: Codable, Sendable, Equatable {
    let app: String
    let taglineEn: String
    let taglineAr: String
    let apiVersion: String
    let serverVersion: String
    let minIosAppVersion: String
    let supportedLanguages: [String]
    let levels: [String]
    let teachers: [TeacherInfo]
    let features: FeatureFlags
}

struct HealthResponse: Codable, Sendable, Equatable {
    let status: String
}

/// Server error envelope: {"error": {code, message, message_ar, request_id}}
struct APIErrorBody: Codable, Sendable, Equatable {
    struct Inner: Codable, Sendable, Equatable {
        let code: String
        let message: String
        let messageAr: String
        let requestId: String?
    }
    let error: Inner
}

enum APIError: Error, Equatable, Sendable {
    case offline
    case timeout
    case server(status: Int, body: APIErrorBody.Inner?)
    case decoding(String)
    case transport(String)

    /// Bilingual, child-friendly message.
    func message(arabic: Bool) -> String {
        switch self {
        case .offline: return arabic ? "لا يوجد اتصال بالإنترنت" : "No internet connection"
        case .timeout: return arabic ? "الخادم لا يستجيب، حاول مرة أخرى" : "The server is not responding. Try again."
        case .server(_, let body?): return arabic ? body.messageAr : body.message
        case .server(let status, nil): return arabic ? "خطأ في الخادم (\(status))" : "Server error (\(status))"
        case .decoding: return arabic ? "استجابة غير متوقعة من الخادم" : "Unexpected server response"
        case .transport: return arabic ? "تعذّر الاتصال بالخادم" : "Could not reach the server"
        }
    }
}

// MARK: - Client

/// Thin async/await HTTP client. Only talks to OUR backend; never to AI providers directly.
final class APIClient: Sendable {
    let baseURL: URL
    private let session: URLSession

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    /// Computed (not a shared static instance) to stay safe under Swift 6 strict concurrency.
    static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    func health() async throws(APIError) -> HealthResponse { try await get("health") }
    func meta() async throws(APIError) -> MetaResponse { try await get("v1/meta") }

    func get<T: Decodable & Sendable>(_ path: String, languageCode: String = "ar") async throws(APIError) -> T {
        var request = URLRequest(url: baseURL.appending(path: path), timeoutInterval: 10)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(languageCode, forHTTPHeaderField: "Accept-Language")
        request.setValue(UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(),
                         forHTTPHeaderField: "X-Request-ID")

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            switch error.code {
            case .notConnectedToInternet, .networkConnectionLost, .dataNotAllowed: throw .offline
            case .timedOut: throw .timeout
            default: throw .transport(error.localizedDescription)
            }
        } catch {
            throw .transport(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else { throw .transport("No HTTP response") }
        guard (200..<300).contains(http.statusCode) else {
            let body = try? Self.decoder.decode(APIErrorBody.self, from: data)
            throw .server(status: http.statusCode, body: body?.error)
        }
        do {
            return try Self.decoder.decode(T.self, from: data)
        } catch {
            throw .decoding(String(describing: error))
        }
    }
}
