/// Backend-authored journey step (Phase 7G). Flutter only renders — no transfer detection.
class JourneyStep {
  final String type; // LEG | TRANSFER
  final String instruction;
  final String? mode;
  final String? fromName;
  final String? toName;
  final String? fromMode;
  final String? toMode;
  final String? locationName;

  const JourneyStep({
    required this.type,
    required this.instruction,
    this.mode,
    this.fromName,
    this.toName,
    this.fromMode,
    this.toMode,
    this.locationName,
  });

  bool get isTransfer => type.toUpperCase() == 'TRANSFER';

  bool get isLeg => type.toUpperCase() == 'LEG';
}
