import 'package:flutter/foundation.dart';

/// Backend configuration. Prefer `--dart-define=API_BASE_URL=...` at run/build.
class AppConfig {
  static const String apiBaseUrlFromDefine = String.fromEnvironment(
    'API_BASE_URL',
  );

  /// Desktop / iOS simulator / web default.
  static const String localDevDefaultBaseUrl = 'http://127.0.0.1:8000';

  /// Android emulator loopback to host machine.
  static const String androidEmulatorDefaultBaseUrl = 'http://10.0.2.2:8000';

  /// Value for the API base URL field at startup.
  /// dart-define always wins; otherwise platform-aware local default.
  static String get initialApiBaseUrl {
    final defined = apiBaseUrlFromDefine.trim();
    if (defined.isNotEmpty) return defined;
    return defaultLocalBaseUrlForPlatform();
  }

  /// Local default for the current Flutter platform (not physical-device LAN IP).
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
    while (url.endsWith('/')) {
      url = url.substring(0, url.length - 1);
    }
    return url;
  }
}
