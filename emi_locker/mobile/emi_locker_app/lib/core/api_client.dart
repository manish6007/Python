import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;

/// An error the backend reported in its own words.
///
/// The backend sends `{"error": "DUPLICATE_DEVICE", "message": "IMEI ... is
/// already on live finance"}`. The message is written for a person, so the app
/// shows it directly instead of inventing its own wording.
class ApiException implements Exception {
  ApiException(this.code, this.message, {this.statusCode});

  final String code;
  final String message;
  final int? statusCode;

  bool get isAuthError => statusCode == 401 || statusCode == 403;

  @override
  String toString() => message;
}

/// Thin wrapper over the EMI Locker API.
///
/// The right default depends on where the code is running, and getting this
/// wrong is the first thing that breaks:
///
/// * **Android emulator** - `10.0.2.2` is the emulator's alias for your own
///   machine. `localhost` there means the emulator itself.
/// * **Flutter web** (the admin panel) - the browser is already on your
///   machine, so `localhost` is correct and `10.0.2.2` means nothing.
///
/// A real phone is neither, so pass your PC's LAN address:
///
///   flutter run --dart-define=API_BASE_URL=http://192.168.1.5:8000
class ApiClient {
  ApiClient({String? baseUrl, http.Client? httpClient})
      : baseUrl = baseUrl ?? defaultBaseUrl(),
        _http = httpClient ?? http.Client();

  static const _configuredBaseUrl =
      String.fromEnvironment('API_BASE_URL', defaultValue: '');

  static String defaultBaseUrl() {
    if (_configuredBaseUrl.isNotEmpty) return _configuredBaseUrl;
    return kIsWeb ? 'http://localhost:8000' : 'http://10.0.2.2:8000';
  }

  final String baseUrl;
  final http.Client _http;

  /// Set once at sign-in and cleared on sign-out.
  String? token;

  Map<String, String> _headers({String? idempotencyKey}) => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
        if (idempotencyKey != null) 'Idempotency-Key': idempotencyKey,
      };

  Future<dynamic> get(String path, {Map<String, String>? query}) =>
      _send(() => _http.get(_uri(path, query), headers: _headers()));

  /// [idempotencyKey] makes a retry safe: the backend returns the result of the
  /// first attempt instead of doing the work twice. Always pass one for
  /// anything that creates a finance, takes money or spends activation quota.
  Future<dynamic> post(
    String path, {
    Map<String, dynamic>? body,
    String? idempotencyKey,
  }) =>
      _send(() => _http.post(
            _uri(path, null),
            headers: _headers(idempotencyKey: idempotencyKey),
            body: jsonEncode(body ?? {}),
          ));

  Future<dynamic> put(String path, {Map<String, dynamic>? body}) =>
      _send(() => _http.put(
            _uri(path, null),
            headers: _headers(),
            body: jsonEncode(body ?? {}),
          ));

  Uri _uri(String path, Map<String, String>? query) =>
      Uri.parse('$baseUrl$path').replace(queryParameters: query);

  Future<dynamic> _send(Future<http.Response> Function() request) async {
    http.Response response;
    try {
      response = await request().timeout(const Duration(seconds: 20));
    } on TimeoutException {
      throw ApiException(
        'NETWORK',
        'The server did not answer in time. Is it still running?',
      );
    } on http.ClientException {
      // What a refused or dropped connection looks like on both targets:
      // ClientException on web, and a SocketException wrapped in one on IO.
      throw ApiException('NETWORK', _unreachableMessage());
    } catch (error) {
      throw ApiException('NETWORK', '$error\n\n${_unreachableMessage()}');
    }

    final text = response.body;
    dynamic decoded;
    if (text.isNotEmpty) {
      try {
        decoded = jsonDecode(text);
      } on FormatException {
        throw ApiException(
          'BAD_RESPONSE',
          'The server sent something the app could not read (HTTP '
              '${response.statusCode}).',
          statusCode: response.statusCode,
        );
      }
    }

    if (response.statusCode >= 200 && response.statusCode < 300) {
      return decoded;
    }

    if (decoded is Map && decoded['message'] != null) {
      throw ApiException(
        decoded['error']?.toString() ?? 'ERROR',
        decoded['message'].toString(),
        statusCode: response.statusCode,
      );
    }
    // FastAPI's own validation errors come back under `detail`.
    if (decoded is Map && decoded['detail'] != null) {
      throw ApiException(
        'VALIDATION_ERROR',
        _readableDetail(decoded['detail']),
        statusCode: response.statusCode,
      );
    }
    throw ApiException(
      'HTTP_${response.statusCode}',
      'Request failed (HTTP ${response.statusCode}).',
      statusCode: response.statusCode,
    );
  }

  String _unreachableMessage() {
    final hint = kIsWeb
        ? 'In a browser the address must be localhost, not 10.0.2.2.'
        : 'On an Android emulator the address must be 10.0.2.2, not localhost.';
    return 'Cannot reach the server at $baseUrl.\n\n'
        'Is the backend running? $hint';
  }

  String _readableDetail(dynamic detail) {
    if (detail is String) return detail;
    if (detail is List && detail.isNotEmpty) {
      final first = detail.first;
      if (first is Map) {
        final field = (first['loc'] as List?)?.last?.toString() ?? 'input';
        return '$field: ${first['msg'] ?? 'is not valid'}';
      }
    }
    return 'Please check what you entered.';
  }
}
