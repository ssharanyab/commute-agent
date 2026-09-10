import 'package:flutter/foundation.dart';

/// Backend configuration. Prefer `--dart-define=API_BASE_URL=...` at run/build.
class AppConfig {
  static const String apiBaseUrlFromDefine = String.fromEnvironment(
    'API_BASE_URL',
  );

  /// Production / demo default (Cloud Run). No trailing path.
  static const String cloudRunDefaultBaseUrl =
      'https://commute-agent-242496011822.asia-south1.run.app';

  /// Desktop / iOS simulator / web local override target.
  static const String localDevDefaultBaseUrl = 'http://127.0.0.1:8000';

  /// Android emulator loopback to host machine.
  static const String androidEmulatorDefaultBaseUrl = 'http://10.0.2.2:8000';

  /// Value for the API base URL field at startup.
  /// dart-define always wins.
  /// Use `--dart-define=API_BASE_URL=relative` for same-origin Cloud Run hosting.
  /// Android debug defaults to the emulator→host loopback: many emulators
  /// cannot resolve Cloud Run DNS (host curl works, app times out).
  static String get initialApiBaseUrl {
    final defined = apiBaseUrlFromDefine.trim();
    if (defined == 'relative' || defined == '.') {
      // Same-origin (FastAPI serves Flutter web). Requests hit /plan, /places/*.
      return '';
    }
    if (defined.isNotEmpty) return defined;
    if (!kIsWeb &&
        kDebugMode &&
        defaultTargetPlatform == TargetPlatform.android) {
      return androidEmulatorDefaultBaseUrl;
    }
    return cloudRunDefaultBaseUrl;
  }

  /// Local default for the current Flutter platform (not physical-device LAN IP).
  /// Use via `--dart-define=API_BASE_URL=...` for local backend development.
  static String defaultLocalBaseUrlForPlatform() {
    if (kIsWeb) return localDevDefaultBaseUrl;
    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return androidEmulatorDefaultBaseUrl;
      default:
        return localDevDefaultBaseUrl;
    }
  }

  static String normalizeBaseUrl(String raw) {
    var url = raw.trim();
    if (url == 'relative' || url == '.') return '';
    while (url.endsWith('/')) {
      url = url.substring(0, url.length - 1);
    }
    return url;
  }

  /// Build an absolute or same-origin [Uri] for [path] (must start with `/`).
  static Uri apiUri(String baseUrl, String path, [Map<String, String>? query]) {
    final base = normalizeBaseUrl(baseUrl);
    final normalizedPath = path.startsWith('/') ? path : '/$path';
    final uri = Uri.parse('$base$normalizedPath');
    if (query == null || query.isEmpty) return uri;
    return uri.replace(queryParameters: query);
  }
}
