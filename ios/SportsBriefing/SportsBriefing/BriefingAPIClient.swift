import Foundation

enum BriefingClientError: Error, Equatable {
    case backendUnavailable
    case noBriefing
    case invalidResponse
    case serverUnavailable

    var message: String {
        switch self {
        case .backendUnavailable:
            "Cannot reach the local backend. Start it and try again."
        case .noBriefing:
            "No Arsenal briefing is available. Run ingestion first."
        case .invalidResponse:
            "The backend returned an unexpected response."
        case .serverUnavailable:
            "The backend could not read the saved briefing."
        }
    }
}

struct BriefingAPIClient {
    private let baseURL: URL
    private let session: URLSession

    init(
        baseURL: URL = URL(string: "http://localhost:8000")!,
        session: URLSession = .shared
    ) {
        self.baseURL = baseURL
        self.session = session
    }

    func fetchArsenalBriefing(hideResults: Bool = true) async throws -> ArsenalBriefing {
        let endpoint = baseURL.appendingPathComponent("briefings/arsenal")
        guard var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false) else {
            throw BriefingClientError.invalidResponse
        }
        components.queryItems = [URLQueryItem(name: "hide_results", value: String(hideResults))]
        guard let url = components.url else {
            throw BriefingClientError.invalidResponse
        }
        let request = URLRequest(url: url, timeoutInterval: 15)

        do {
            let (data, response) = try await session.data(for: request)
            let briefing = try Self.decode(data: data, response: response)
            try Self.validate(briefing, requestedHideResults: hideResults)
            return briefing
        } catch let error as BriefingClientError {
            throw error
        } catch {
            throw Self.mapTransportError(error)
        }
    }

    static func decode(data: Data, response: URLResponse) throws -> ArsenalBriefing {
        guard let response = response as? HTTPURLResponse else {
            throw BriefingClientError.invalidResponse
        }
        switch response.statusCode {
        case 200:
            break
        case 404:
            throw BriefingClientError.noBriefing
        case 503:
            throw BriefingClientError.serverUnavailable
        default:
            throw BriefingClientError.invalidResponse
        }

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let value = try decoder.singleValueContainer().decode(String.self)
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: value) {
                return date
            }
            formatter.formatOptions = [.withInternetDateTime]
            if let date = formatter.date(from: value) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: try decoder.singleValueContainer(),
                debugDescription: "Expected an ISO-8601 UTC timestamp"
            )
        }
        do {
            return try decoder.decode(ArsenalBriefing.self, from: data)
        } catch {
            throw BriefingClientError.invalidResponse
        }
    }

    static func mapTransportError(_ error: Error) -> BriefingClientError {
        if error is URLError {
            return .backendUnavailable
        }
        return .invalidResponse
    }

    static func validate(
        _ briefing: ArsenalBriefing,
        requestedHideResults: Bool
    ) throws {
        guard requestedHideResults else {
            return
        }
        let latest = briefing.latestCompletedMatch
        guard briefing.spoiler.resultsHidden,
              latest?.result == nil,
              latest?.resultHidden != false else {
            throw BriefingClientError.invalidResponse
        }
    }
}
