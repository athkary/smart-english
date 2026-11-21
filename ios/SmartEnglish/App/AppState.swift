import Foundation
import Observation

enum ConnectionState: Equatable {
    case checking
    case connected(MetaResponse)
    case updateRequired(minimum: String)
    case failed(APIError)
}

/// App-wide state. Phase 1: backend connectivity + server-advertised capabilities.
@MainActor
@Observable
final class AppState {
    private(set) var connection: ConnectionState = .checking
    @ObservationIgnored let environment: AppEnvironment
    @ObservationIgnored private let api: APIClient

    init(environment: AppEnvironment = .fromBundle(), api: APIClient? = nil) {
        self.environment = environment
        self.api = api ?? APIClient(baseURL: environment.apiBaseURL)
    }

    var meta: MetaResponse? {
        if case .connected(let m) = connection { return m }
        return nil
    }

    func refresh() async {
        connection = .checking
        do {
            _ = try await api.health()
            let meta = try await api.meta()
            if VersionCompare.isAtLeast(environment.appVersion, minimum: meta.minIosAppVersion) {
                connection = .connected(meta)
            } else {
                connection = .updateRequired(minimum: meta.minIosAppVersion)
            }
        } catch {
            connection = .failed(error)
        }
    }
}
