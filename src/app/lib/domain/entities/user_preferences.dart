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

/// Soft preference profiles mapped to backend Decision Engine names.
enum OptimizationProfile {
  balanced,
  fastest,
  cheapest,
  lessWalking,
  moreReliable,
  lowerTraffic,
}

extension OptimizationProfileWeights on OptimizationProfile {
  String get label {
    switch (this) {
      case OptimizationProfile.balanced:
        return 'Balanced';
      case OptimizationProfile.fastest:
        return 'Fastest';
      case OptimizationProfile.cheapest:
        return 'Cheapest';
      case OptimizationProfile.lessWalking:
        return 'Less walking';
      case OptimizationProfile.moreReliable:
        return 'More reliable';
      case OptimizationProfile.lowerTraffic:
        return 'Lower traffic';
    }
  }

  /// Backend Decision Engine profile name (soft weights only).
  String get preferenceProfileName {
    switch (this) {
      case OptimizationProfile.balanced:
        return 'BALANCED';
      case OptimizationProfile.fastest:
        return 'FASTEST';
      case OptimizationProfile.cheapest:
        return 'CHEAPEST';
      case OptimizationProfile.lessWalking:
        return 'LOW_WALKING';
      case OptimizationProfile.moreReliable:
        return 'RELIABLE';
      case OptimizationProfile.lowerTraffic:
        return 'LOW_TRAFFIC';
    }
  }

  UserPreferences toWeights({
    required bool avoidHeavyTraffic,
    double? maxWalkingMinutes,
    List<String> excludedModes = const [],
  }) {
    switch (this) {
      case OptimizationProfile.balanced:
        return UserPreferences(
          avoidHeavyTraffic: avoidHeavyTraffic,
          maxWalkingMinutes: maxWalkingMinutes,
          excludedModes: excludedModes,
          timeWeight: 1.0,
          costWeight: 1.0,
          walkingWeight: 1.0,
          transferWeight: 1.0,
          congestionWeight: 1.0,
          reliabilityWeight: 1.0,
        );
      case OptimizationProfile.fastest:
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
      case OptimizationProfile.cheapest:
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
      case OptimizationProfile.lessWalking:
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
      case OptimizationProfile.moreReliable:
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
      case OptimizationProfile.lowerTraffic:
        return UserPreferences(
          avoidHeavyTraffic: avoidHeavyTraffic,
          maxWalkingMinutes: maxWalkingMinutes,
          excludedModes: excludedModes,
          timeWeight: 1.0,
          costWeight: 1.0,
          walkingWeight: 1.0,
          transferWeight: 1.0,
          congestionWeight: 8.0,
          reliabilityWeight: 1.0,
        );
    }
  }
}
