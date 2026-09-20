import Foundation

struct ArsenalBriefing: Decodable, Equatable, Sendable {
    let entity: BriefingEntity
    let headline: String
    let summary: String
    let reasonShown: String
    let asOf: Date
    let spoiler: SpoilerState
    let nextMatch: BriefingMatch?
    let latestCompletedMatch: BriefingMatch?
    let source: BriefingSource
}

struct BriefingEntity: Decodable, Equatable, Sendable {
    let id: String
    let name: String
}

struct SpoilerState: Decodable, Equatable, Sendable {
    let resultsHidden: Bool
}

struct BriefingMatch: Decodable, Equatable, Sendable {
    let competition: Competition
    let kickoffUtc: Date
    let status: String
    let homeTeam: String
    let awayTeam: String
    let provenance: MatchProvenance
    let resultHidden: Bool?
    let result: MatchResult?
}

struct Competition: Decodable, Equatable, Sendable {
    let code: String
    let name: String
}

struct MatchProvenance: Decodable, Equatable, Sendable {
    let providerUpdatedAt: Date
    let observedAt: Date
}

struct MatchResult: Decodable, Equatable, Sendable {
    let fullTime: FullTimeScore
    let winner: String?
    let duration: String?
}

struct FullTimeScore: Decodable, Equatable, Sendable {
    let home: Int?
    let away: Int?
}

struct BriefingSource: Decodable, Equatable, Sendable {
    let provider: String
    let attribution: String
    let checkedAt: Date
}
