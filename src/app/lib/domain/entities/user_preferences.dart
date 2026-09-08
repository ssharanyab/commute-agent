class UserPreferences {
  final bool avoidHeavyTraffic;
  final double? maxWalkingMinutes;
  final double? maxCost;
  final List<String> excludedModes;
  final double? timeWeight;
  final double? costWeight;
  final double? walkingWeight;
  final double? transferWeight;
  final double? congestionWeight;
  final double? reliabilityWeight;

  const UserPreferences({
    this.avoidHeavyTraffic = true,
    this.maxWalkingMinutes,
    this.maxCost,
    this.excludedModes = const [],
    this.timeWeight,
    this.costWeight,
    this.walkingWeight,
    this.transferWeight,
    this.congestionWeight,
    this.reliabilityWeight,
  });
}

/// Soft optimization profiles mapped to backend preference weights.
enum OptimizationProfile { fast, cheap, reliable, easy }

extension OptimizationProfileWeights on OptimizationProfile {
  String get label {
    switch (this) {
      case OptimizationProfile.fast:
        return 'Fast';
      case OptimizationProfile.cheap:
        return 'Cheap';
      case OptimizationProfile.reliable:
        return 'Reliable';
      case OptimizationProfile.easy:
        return 'Easy';
    }
  }

  UserPreferences toWeights({
    required bool avoidHeavyTraffic,
    double? maxWalkingMinutes,
    List<String> excludedModes = const [],
  }) {
    switch (this) {
      case OptimizationProfile.fast:
        return UserPreferences(
          avoidHeavyTraffic: avoidHeavyTraffic,
          maxWalkingMinutes: maxWalkingMinutes,
          excludedModes: excludedModes,
          timeWeight: 8.0,
          costWeight: 1.0,
          walkingWeight: 1.0,
          transferWeight: 1.0,
          congestionWeight: 1.0,
          reliabilityWeight: 1.0,
        );
      case OptimizationProfile.cheap:
        return UserPreferences(
          avoidHeavyTraffic: avoidHeavyTraffic,
          maxWalkingMinutes: maxWalkingMinutes,
          excludedModes: excludedModes,
          timeWeight: 1.0,
          costWeight: 8.0,
          walkingWeight: 1.0,
          transferWeight: 1.0,
          congestionWeight: 1.0,
          reliabilityWeight: 1.0,
        );
      case OptimizationProfile.reliable:
        return UserPreferences(
          avoidHeavyTraffic: avoidHeavyTraffic,
          maxWalkingMinutes: maxWalkingMinutes,
          excludedModes: excludedModes,
          timeWeight: 1.0,
          costWeight: 1.0,
          walkingWeight: 1.0,
          transferWeight: 1.0,
          congestionWeight: 1.0,
          reliabilityWeight: 8.0,
        );
      case OptimizationProfile.easy:
        return UserPreferences(
          avoidHeavyTraffic: avoidHeavyTraffic,
          maxWalkingMinutes: maxWalkingMinutes,
          excludedModes: excludedModes,
          timeWeight: 1.0,
          costWeight: 1.0,
          walkingWeight: 8.0,
          transferWeight: 4.0,
          congestionWeight: 1.0,
          reliabilityWeight: 1.0,
        );
    }
  }
}
