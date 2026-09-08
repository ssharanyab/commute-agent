class ApiException implements Exception {
  final int? statusCode;
  final String message;
  final String? errorCode;
  final Map<String, dynamic>? body;

  ApiException({
    required this.message,
    this.statusCode,
    this.errorCode,
    this.body,
  });

  @override
  String toString() => message;
}
