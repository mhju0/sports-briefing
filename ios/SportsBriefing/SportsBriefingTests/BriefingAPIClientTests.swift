import Foundation
import Testing
@testable import SportsBriefing

struct BriefingAPIClientTests {
    @Test
    func `decodes hidden briefing with fractional and whole-second UTC timestamps`() throws {
        let response = try #require(HTTPURLResponse(
            url: URL(string: "http://localhost:8000/briefings/arsenal")!,
            statusCode: 200,
            httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        ))

        let briefing = try BriefingAPIClient.decode(
            data: Data(Self.hiddenJSON.utf8),
            response: response
        )

        #expect(briefing.entity.name == "Arsenal")
        #expect(briefing.nextMatch?.competition.code == "CL")
        #expect(briefing.nextMatch?.kickoffUtc.timeIntervalSince1970 == 1_790_190_000)
        #expect(abs(briefing.asOf.timeIntervalSince1970 - 1_789_897_759.148699) < 0.001)
        #expect(briefing.latestCompletedMatch?.resultHidden == true)
        #expect(briefing.latestCompletedMatch?.result == nil)
    }

    @Test
    func `decodes revealed result only when supplied by the API`() throws {
        let response = try #require(HTTPURLResponse(
            url: URL(string: "http://localhost:8000/briefings/arsenal")!,
            statusCode: 200,
            httpVersion: nil,
            headerFields: nil
        ))

        let briefing = try BriefingAPIClient.decode(
            data: Data(Self.revealedJSON.utf8),
            response: response
        )

        #expect(briefing.spoiler.resultsHidden == false)
        #expect(briefing.latestCompletedMatch?.result?.fullTime.home == 3)
        #expect(briefing.latestCompletedMatch?.result?.fullTime.away == 0)
    }

    @Test
    func `rejects revealed payload when hidden results were requested`() throws {
        let response = try #require(HTTPURLResponse(
            url: URL(string: "http://localhost:8000/briefings/arsenal")!,
            statusCode: 200,
            httpVersion: nil,
            headerFields: nil
        ))
        let briefing = try BriefingAPIClient.decode(
            data: Data(Self.revealedJSON.utf8),
            response: response
        )

        #expect(throws: BriefingClientError.invalidResponse) {
            try BriefingAPIClient.validate(briefing, requestedHideResults: true)
        }
    }

    @Test(arguments: [404, 503])
    func `maps controlled server failures to distinct client errors`(statusCode: Int) throws {
        let response = try #require(HTTPURLResponse(
            url: URL(string: "http://localhost:8000/briefings/arsenal")!,
            statusCode: statusCode,
            httpVersion: nil,
            headerFields: nil
        ))

        let expected: BriefingClientError = statusCode == 404 ? .noBriefing : .serverUnavailable
        #expect(throws: expected) {
            try BriefingAPIClient.decode(data: Data("{}".utf8), response: response)
        }
    }

    @Test
    func `reports malformed success payload separately`() throws {
        let response = try #require(HTTPURLResponse(
            url: URL(string: "http://localhost:8000/briefings/arsenal")!,
            statusCode: 200,
            httpVersion: nil,
            headerFields: nil
        ))

        #expect(throws: BriefingClientError.invalidResponse) {
            try BriefingAPIClient.decode(data: Data("{\"unexpected\":true}".utf8), response: response)
        }
    }

    @Test
    func `maps connection failures to backend unavailable`() {
        #expect(
            BriefingAPIClient.mapTransportError(URLError(.cannotConnectToHost))
                == .backendUnavailable
        )
    }

    private static let hiddenJSON = """
    {
      "entity":{"id":"arsenal","name":"Arsenal"},
      "headline":"Arsenal FC vs FC Bayern Muenchen",
      "summary":"Next match in UEFA Champions League at 2026-09-23T19:00:00Z.",
      "reason_shown":"Next scheduled match",
      "as_of":"2026-09-20T09:49:19.148699Z",
      "spoiler":{"results_hidden":true},
      "next_match":{
        "competition":{"code":"CL","name":"UEFA Champions League"},
        "kickoff_utc":"2026-09-23T19:00:00Z",
        "status":"TIMED",
        "home_team":"FC Bayern Muenchen",
        "away_team":"Arsenal FC",
        "provenance":{"provider_updated_at":"2026-09-19T10:00:00Z","observed_at":"2026-09-20T09:49:19.148699Z"}
      },
      "latest_completed_match":{
        "competition":{"code":"PL","name":"Premier League"},
        "kickoff_utc":"2026-09-13T15:30:00Z",
        "status":"FINISHED",
        "home_team":"Arsenal FC",
        "away_team":"Nottingham Forest FC",
        "provenance":{"provider_updated_at":"2026-09-13T17:40:00Z","observed_at":"2026-09-20T09:49:19Z"},
        "result_hidden":true
      },
      "source":{"provider":"football-data.org","attribution":"Football data provided by the Football-Data.org API","checked_at":"2026-09-20T09:49:19.148699Z"}
    }
    """

    private static let revealedJSON = hiddenJSON
        .replacingOccurrences(of: "\"results_hidden\":true", with: "\"results_hidden\":false")
        .replacingOccurrences(
            of: "\"result_hidden\":true",
            with: "\"result_hidden\":false,\"result\":{\"full_time\":{\"home\":3,\"away\":0},\"winner\":\"HOME_TEAM\",\"duration\":\"REGULAR\"}"
        )
}
