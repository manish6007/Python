import 'dart:convert';

import 'package:emi_locker_app/core/api_client.dart';
import 'package:emi_locker_app/core/session.dart';
import 'package:emi_locker_app/main.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'helpers.dart';

/// A previous sign-in, as restore() finds it on launch.
void savedSignIn(Map<String, dynamic> user) {
  SharedPreferences.setMockInitialValues({
    'emi.token': 'saved-token',
    'emi.user': jsonEncode(user),
  });
}

void main() {
  group('restore', () {
    test('keeps a saved sign-in when the server cannot be reached', () async {
      savedSignIn(customerUser);
      final api = ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((_) async => throw http.ClientException('refused')),
      );
      final session = Session(api);

      await session.restore();

      // A 30-day session must survive one launch on a bad signal.
      expect(session.isSignedIn, isTrue);
      expect(session.displayName, 'Ramesh Kumar');
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('emi.token'), 'saved-token');
    });

    test('ends a saved sign-in the server rejects', () async {
      savedSignIn(customerUser);
      final fake = FakeApi({
        'GET /auth/me': (_) => errorResponse(
            401, 'SESSION_INVALID', 'this session was ended, please sign in again'),
      });
      final session = Session(
          ApiClient(baseUrl: 'http://test.local', httpClient: fake.client));

      await session.restore();

      expect(session.isSignedIn, isFalse);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('emi.token'), isNull);
    });
  });

  group('a session ended while the app is open', () {
    testWidgets('returns to sign-in and says why', (tester) async {
      useTallSurface(tester);
      savedSignIn(retailerUser);
      final fake = FakeApi({
        'GET /auth/me': (_) => retailerUser,
        'GET /retailer/dashboard': (_) => errorResponse(
            401, 'SESSION_INVALID', 'this session was ended, please sign in again'),
      });

      await tester.pumpWidget(EmiLockerApp(
          api: ApiClient(baseUrl: 'http://test.local', httpClient: fake.client)));
      await tester.pumpAndSettle();

      // Not a dead-end error with a "Try again" that can never work.
      expect(find.text('Send OTP'), findsOneWidget);
      expect(find.text('Try again'), findsNothing);
      expect(find.text('this session was ended, please sign in again'),
          findsOneWidget);
    });

    testWidgets('a refusal is not a sign-out', (tester) async {
      useTallSurface(tester);
      savedSignIn(retailerUser);
      final fake = FakeApi({
        'GET /auth/me': (_) => retailerUser,
        'GET /retailer/dashboard': (_) =>
            errorResponse(403, 'PERMISSION_DENIED', 'not your retailer'),
      });

      await tester.pumpWidget(EmiLockerApp(
          api: ApiClient(baseUrl: 'http://test.local', httpClient: fake.client)));
      await tester.pumpAndSettle();

      expect(find.text('Send OTP'), findsNothing);
      expect(find.text('not your retailer'), findsOneWidget);
    });
  });

  test('a wrong code while signing in does not count as a session', () async {
    SharedPreferences.setMockInitialValues({});
    final fake = FakeApi({
      'POST /auth/verify-otp': (_) =>
          errorResponse(401, 'SESSION_INVALID', 'sign in to continue'),
    });
    final api = ApiClient(baseUrl: 'http://test.local', httpClient: fake.client);
    var ended = false;
    api.onSessionInvalid = (_) => ended = true;

    await expectLater(api.post('/auth/verify-otp'), throwsA(isA<ApiException>()));
    expect(ended, isFalse);
  });
}
