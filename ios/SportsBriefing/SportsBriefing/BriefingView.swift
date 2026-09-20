import Observation
import SwiftUI

enum BriefingLoadState: Equatable {
    case loading
    case loaded(ArsenalBriefing)
    case failed(BriefingClientError)
}

@Observable
final class BriefingStore {
    private let client: BriefingAPIClient
    private(set) var state: BriefingLoadState = .loading

    init(client: BriefingAPIClient = BriefingAPIClient()) {
        self.client = client
    }

    func load(hideResults: Bool = true) async {
        state = .loading
        do {
            state = .loaded(try await client.fetchArsenalBriefing(hideResults: hideResults))
        } catch let error as BriefingClientError {
            state = .failed(error)
        } catch {
            state = .failed(.invalidResponse)
        }
    }
}

struct BriefingView: View {
    @State private var store = BriefingStore()

    var body: some View {
        Group {
            switch store.state {
            case .loading:
                ProgressView("Loading Arsenal briefing…")
            case .loaded(let briefing):
                briefingContent(briefing)
            case .failed(let error):
                errorContent(error)
            }
        }
        .task {
            await store.load()
        }
    }

    private func briefingContent(_ briefing: ArsenalBriefing) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(briefing.entity.name)
                        .font(.largeTitle.bold())
                    Text(briefing.headline)
                        .font(.title2.weight(.semibold))
                    Text(briefing.summary)
                        .foregroundStyle(.secondary)
                    Text(briefing.reasonShown)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                }

                if let nextMatch = briefing.nextMatch {
                    matchSection(title: "Next match", match: nextMatch)
                }

                if let latestMatch = briefing.latestCompletedMatch {
                    latestSection(match: latestMatch, resultsHidden: briefing.spoiler.resultsHidden)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(briefing.source.attribution)
                    Text("Checked \(briefing.source.checkedAt.formatted(date: .abbreviated, time: .shortened))")
                    Text("Saved briefing evaluated \(briefing.asOf.formatted(date: .abbreviated, time: .shortened))")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }
        .refreshable {
            await store.load(hideResults: briefing.spoiler.resultsHidden)
        }
    }

    private func matchSection(title: String, match: BriefingMatch) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
            Text(match.competition.name)
                .foregroundStyle(.secondary)
            Text("\(match.homeTeam) vs \(match.awayTeam)")
                .font(.body.weight(.medium))
            Text(match.kickoffUtc.formatted(date: .abbreviated, time: .shortened))
            Text(match.status.replacingOccurrences(of: "_", with: " ").capitalized)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text("Observed \(match.provenance.observedAt.formatted(date: .abbreviated, time: .shortened))")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func latestSection(match: BriefingMatch, resultsHidden: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Latest completed match")
                .font(.headline)
            Text(match.competition.name)
                .foregroundStyle(.secondary)
            Text("\(match.homeTeam) vs \(match.awayTeam)")
                .font(.body.weight(.medium))
            Text(match.kickoffUtc.formatted(date: .abbreviated, time: .shortened))
            if resultsHidden {
                Text("Result hidden")
                    .foregroundStyle(.secondary)
                Button("Reveal result") {
                    Task { await store.load(hideResults: false) }
                }
            } else if let result = match.result {
                Text(scoreText(result.fullTime))
                    .font(.title3.monospacedDigit().weight(.semibold))
                if let duration = result.duration {
                    Text(duration.replacingOccurrences(of: "_", with: " ").capitalized)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Text("Observed \(match.provenance.observedAt.formatted(date: .abbreviated, time: .shortened))")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func scoreText(_ score: FullTimeScore) -> String {
        guard let home = score.home, let away = score.away else {
            return "Score unavailable"
        }
        return "\(home) – \(away)"
    }

    private func errorContent(_ error: BriefingClientError) -> some View {
        ContentUnavailableView {
            Label("Briefing unavailable", systemImage: "exclamationmark.triangle")
        } description: {
            Text(error.message)
        } actions: {
            Button("Try again") {
                Task { await store.load() }
            }
        }
    }
}
