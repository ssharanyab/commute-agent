enum ApiErrorKind {
  network,
  malformed,
  backend,
  unknown,
}

class ApiException implements Exception {
  final int? statusCode;
  final String message;
  final String? errorCode;
  final Map<String, dynamic>? body;
  final ApiErrorKind kind;

  ApiException({
    required this.message,
    this.statusCode,
    this.errorCode,
    this.body,
    this.kind = ApiErrorKind.unknown,
  });

  factory ApiException.network(String message) => ApiException(
        message: message,
        kind: ApiErrorKind.network,
      );

  factory ApiException.malformed(String message, {int? statusCode}) =>
      ApiException(
        message: message,
        statusCode: statusCode,
        kind: ApiErrorKind.malformed,
      );

  @override
  String toString() => message;
}
