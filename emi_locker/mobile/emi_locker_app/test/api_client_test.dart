import 'dart:convert';

import 'package:emi_locker_app/core/api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'helpers.dart';

void main() {
  test('shows the backend message rather than inventing its own', () async {
    final fake = FakeApi({
      'POST /finance': (_) => errorResponse(409, 'DUPLICATE_DEVICE',
          'IMEI 490154203237518 is already on live finance (device DEV-1, ACTIVE)'),
    });
    final api = ApiClient(baseUrl: 'http://test.local', httpClient: fake.client);

    await expectLater(
      api.post('/finance'),
      throwsA(isA<ApiException>()
          .having((e) => e.code, 'code', 'DUPLICATE_DEVICE')
          .having((e) => e.message, 'message', contains('already on live finance'))
          .having((e) => e.statusCode, 'status', 409)),
    );
  });

  test('turns a FastAPI validation error into something readable', () async {
    final fake = FakeApi({
      'POST /finance': (_) => http.Response(
          jsonEncode({
            'detail': [
              {'loc': ['body', 'tenure_months'], 'msg': 'must be greater than 0'}
            ]
          }),
          422,
          headers: {'content-type': 'application/json'}),
    });
    final api = ApiClient(baseUrl: 'http://test.local', httpClient: fake.client);
    await expectLater(
      api.post('/finance'),
      throwsA(isA<ApiException>()
          .having((e) => e.message, 'message', contains('tenure_months'))),
    );
  });

  test('sends the bearer token once signed in, and not before', () async {
    final fake = FakeApi({'GET /auth/me': (_) => {'id': 'USR-1'}});
    final api = ApiClient(baseUrl: 'http://test.local', httpClient: fake.client);

    await api.get('/auth/me');
    expect(fake.headers.last.containsKey('Authorization'), isFalse);

    api.token = 'abc123';
    await api.get('/auth/me');
    expect(fake.headers.last['Authorization'], 'Bearer abc123');
  });

  test('passes the idempotency key through so a retry is safe', () async {
    final fake = FakeApi({'POST /collections': (_) => {'payment_id': 'PAY-1'}});
    final api = ApiClient(baseUrl: 'http://test.local', httpClient: fake.client);

    await api.post('/collections', body: {'a': 1}, idempotencyKey: 'cash-42');
    expect(fake.headers.last['Idempotency-Key'], 'cash-42');
  });

  test('explains an unreachable server in terms a beginner can act on', () async {
    final api = ApiClient(baseUrl: 'http://127.0.0.1:1', httpClient: null);
    try {
      await api.get('/health');
      fail('expected a network failure');
    } on ApiException catch (error) {
      expect(error.code, 'NETWORK');
      expect(error.message, contains('10.0.2.2'));
    }
  });
}
