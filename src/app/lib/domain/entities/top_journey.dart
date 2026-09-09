import '../entities/value_status.dart';
import 'journey_step.dart';

/// Backend Top-5 option (Phase 7C/7D). Presentation only — Flutter does not rank.
class TopJourneyOption {
  final String routeId;
  final String candidateId;
  final String mode;
  final String modeSignature;
  final String diversitySignature;
  final List<String> componentModes;
  final double? duration;
  final double? cost;
  final ValueStatus costStatus;
  final ValueStatus durationStatus;
  final double? walkingDistanceMeters;
  final int transfers;
  final double score;
  final int rank;
  final int strategyTier;
  final bool isRecommended;
  final String reason;
  final String backbone;
  final List<JourneyStep> steps;

  const TopJourneyOption({
    required this.routeId,
    required this.candidateId,
    required this.mode,
    this.modeSignature = '',
    this.diversitySignature = '',
    this.componentModes = const [],
    this.duration,
    this.cost,
    this.costStatus = ValueStatus.known,
    this.durationStatus = ValueStatus.known,
    this.walkingDistanceMeters,
    this.transfers = 0,
    this.score = 0,
    this.rank = 0,
    this.strategyTier = 0,
    this.isRecommended = false,
    this.reason = '',
    this.backbone = '',
    this.steps = const [],
  });

  bool get hasKnownCost => costStatus == ValueStatus.known;

  bool get hasKnownDuration => durationStatus == ValueStatus.known;

  bool get hasKnownWalking => walkingDistanceMeters != null;

  String get identity =>
      candidateId.isNotEmpty ? candidateId : routeId;
}

class TopJourneySelection {
  final TopJourneyOption? recommended;
  final List<TopJourneyOption> alternatives;
  final int selectedCount;
  final int maxCount;
  final List<TopJourneyOption> topJourneys;

  const TopJourneySelection({
    this.recommended,
    this.alternatives = const [],
    this.selectedCount = 0,
    this.maxCount = 5,
    this.topJourneys = const [],
  });

  bool get isEmpty => topJourneys.isEmpty && recommended == null;

  /// Cap display at five; never invent placeholders.
  List<TopJourneyOption> get displayJourneys {
    final source =
        topJourneys.isNotEmpty ? topJourneys : _fromParts();
    if (source.length <= 5) return source;
    return source.take(5).toList(growable: false);
  }

  List<TopJourneyOption> _fromParts() {
    final out = <TopJourneyOption>[];
    if (recommended != null) out.add(recommended!);
    out.addAll(alternatives);
    return out;
  }
}
