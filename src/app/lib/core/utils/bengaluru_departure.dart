// Bengaluru / Asia/Kolkata (IST, UTC+05:30) departure helpers for the MVP UI.
// API payload remains ISO-8601; Maps integration converts to UTC.

/// Result of validating/rebuilding departure at PLAN time.
class PlanDeparture {
  final String displayIst;
  final String apiIso8601;
  final bool adjusted;

  const PlanDeparture({
    required this.displayIst,
    required this.apiIso8601,
    required this.adjusted,
  });
}

class BengaluruDeparture {
  static const Duration istOffset = Duration(hours: 5, minutes: 30);

  /// Departures within this window of "now" are treated as too close for Maps.
  static const Duration minFutureSkew = Duration(seconds: 60);

  /// Current wall-clock time in IST (as a timezone-agnostic DateTime).
  static DateTime nowIst([DateTime? utcNow]) {
    final utc = (utcNow ?? DateTime.now()).toUtc();
    return utc.add(istOffset);
  }

  /// Default demo departure: IST now + [ahead], formatted for the text field.
  static String defaultDisplay({
    Duration ahead = const Duration(hours: 1),
    DateTime? utcNow,
  }) {
    return formatIstDisplay(nowIst(utcNow).add(ahead));
  }

  /// Display format: `yyyy-MM-dd HH:mm` (Bengaluru local).
  static String formatIstDisplay(DateTime istWallClock) {
    final y = istWallClock.year.toString().padLeft(4, '0');
    final m = istWallClock.month.toString().padLeft(2, '0');
    final d = istWallClock.day.toString().padLeft(2, '0');
    final h = istWallClock.hour.toString().padLeft(2, '0');
    final min = istWallClock.minute.toString().padLeft(2, '0');
    return '$y-$m-$d $h:$min';
  }

  /// Convert user input to ISO-8601 for the API.
  ///
  /// - Naive / IST display strings → `…+05:30`
  /// - Strings that already include `Z` or an offset → normalized UTC `…Z`
  static String toApiIso8601(String input) {
    final trimmed = input.trim();
    if (trimmed.isEmpty) {
      throw FormatException('Empty departure time');
    }

    if (_hasExplicitOffset(trimmed)) {
      final parsed = DateTime.parse(_normalizeIsoForParse(trimmed));
      return _formatUtcZ(parsed.toUtc());
    }

    final wall = parseIstWallClock(trimmed);
    return '${_datePart(wall)}T${_timePart(wall)}+05:30';
  }

  /// Validate at PLAN time: past / too-close / empty / invalid → IST now + 1h.
  static PlanDeparture resolveForPlan(
    String input, {
    DateTime? utcNow,
    Duration ahead = const Duration(hours: 1),
  }) {
    final now = (utcNow ?? DateTime.now()).toUtc();
    final threshold = now.add(minFutureSkew);
    final trimmed = input.trim();
    if (trimmed.isEmpty) {
      final display = defaultDisplay(ahead: ahead, utcNow: now);
      return PlanDeparture(
        displayIst: display,
        apiIso8601: toApiIso8601(display),
        adjusted: true,
      );
    }

    try {
      final iso = toApiIso8601(trimmed);
      final departureUtc = DateTime.parse(_normalizeIsoForParse(iso)).toUtc();
      if (!departureUtc.isBefore(threshold)) {
        return PlanDeparture(
          displayIst: trimmed,
          apiIso8601: iso,
          adjusted: false,
        );
      }
    } on FormatException {
      // fall through to bump
    } on ArgumentError {
      // fall through to bump
    }

    final display = defaultDisplay(ahead: ahead, utcNow: now);
    return PlanDeparture(
      displayIst: display,
      apiIso8601: toApiIso8601(display),
      adjusted: true,
    );
  }

  /// Parse Bengaluru local wall clock from common UI forms.
  static DateTime parseIstWallClock(String input) {
    var s = input.trim();
    s = s.replaceFirst(RegExp(r'\s*IST\s*$', caseSensitive: false), '');
    s = s.replaceFirst(' ', 'T');
    final match = RegExp(
      r'^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$',
    ).firstMatch(s);
    if (match == null) {
      throw FormatException('Invalid IST departure: $input');
    }
    return DateTime(
      int.parse(match.group(1)!),
      int.parse(match.group(2)!),
      int.parse(match.group(3)!),
      int.parse(match.group(4)!),
      int.parse(match.group(5)!),
      int.parse(match.group(6) ?? '0'),
    );
  }

  static bool _hasExplicitOffset(String s) {
    return RegExp(r'(Z|[+-]\d{2}:?\d{2})$').hasMatch(s);
  }

  static String _normalizeIsoForParse(String s) {
    // Allow "+0530" → "+05:30" for DateTime.parse.
    return s.replaceFirstMapped(
      RegExp(r'([+-])(\d{2})(\d{2})$'),
      (m) => '${m[1]}${m[2]}:${m[3]}',
    );
  }

  static String _formatUtcZ(DateTime utc) {
    final u = utc.toUtc();
    return '${_datePart(u)}T${_timePart(u)}Z';
  }

  static String _datePart(DateTime dt) {
    final y = dt.year.toString().padLeft(4, '0');
    final m = dt.month.toString().padLeft(2, '0');
    final d = dt.day.toString().padLeft(2, '0');
    return '$y-$m-$d';
  }

  static String _timePart(DateTime dt) {
    final h = dt.hour.toString().padLeft(2, '0');
    final min = dt.minute.toString().padLeft(2, '0');
    final sec = dt.second.toString().padLeft(2, '0');
    return '$h:$min:$sec';
  }
}
