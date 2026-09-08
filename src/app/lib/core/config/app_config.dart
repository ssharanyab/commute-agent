/// Backend configuration. Prefer `--dart-define=API_BASE_URL=...` at run/build.
/// When the define is empty, the UI prefills a local development default only.
class AppConfig {
  static const String apiBaseUrlFromDefine = String.fromEnvironment(
    'API_BASE_URL',
  );

  /// Local macOS/desktop default when no dart-define is set.
  /// Android emulator should pass `--dart-define=API_BASE_URL=http://10.0.2.2:8000`.
  static const String localDevDefaultBaseUrl = 'http://127.0.0.1:8000';

  /// Value for the API base URL field at startup.
  /// dart-define always wins over the local default.
  static String get initialApiBaseUrl {
    final defined = apiBaseUrlFromDefine.trim();
    if (defined.isNotEmpty) return defined;
    return localDevDefaultBaseUrl;
  }

  static String normalizeBaseUrl(String raw) {
    var url = raw.trim();
    while (url.endsWith('/')) {
      url = url.substring(0, url.length - 1);
    }
    return url;
  }
}
