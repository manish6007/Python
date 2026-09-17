import 'dart:convert';

import 'package:emi_locker_app/core/api_client.dart';
import 'package:emi_locker_app/core/session.dart';
import 'package:emi_locker_app/core/theme.dart';
import 'package:emi_locker_app/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// A stand-in backend. Routes are matched on `METHOD /path`, and every request
/// is recorded so a test can assert on what the app actually sent - which is
/// the only way to prove, for example, that the app never claims a payment
/// succeeded by itself.
class FakeApi {
  FakeApi(this.routes);

  final Map<String, dynamic Function(Map<String, dynamic> body)> routes;
  final List<String> calls = [];
  final List<Map<String, dynamic>> bodies = [];
  final List<Map<String, String>> headers = [];

  /// The body of the first request matching `METHOD /path`.
  ///
  /// Screens usually reload after a write, so `bodies.last` is the follow-up
  /// GET rather than the write you meant to inspect.
  Map<String, dynamic> bodyFor(String call) => bodies[_indexOf(call)];

  Map<String, String> headersFor(String call) => headers[_indexOf(call)];

  int countOf(String call) => calls.where((c) => c == call).length;

  int _indexOf(String call) {
    final index = calls.indexOf(call);
    if (index < 0) {
      throw StateError('no request matched "\$call"; saw: \$calls');
    }
    return index;
  }

  http.Client get client => MockClient((request) async {
        final key = '${request.method} ${request.url.path}';
        calls.add(key);
        headers.add(request.headers);
        final body = request.body.isEmpty
            ? <String, dynamic>{}
            : Map<String, dynamic>.from(jsonDecode(request.body) as Map);
        bodies.add(body);

        final handler = routes[key];
        if (handler == null) {
          return http.Response(
            jsonEncode({'error': 'NOT_FOUND', 'message': 'no fake route for $key'}),
            404,
            headers: {'content-type': 'application/json'},
          );
        }
        final result = handler(body);
        if (result is http.Response) return result;
        return http.Response(jsonEncode(result), 200,
            headers: {'content-type': 'application/json'});
      });
}

http.Response errorResponse(int status, String code, String message) =>
    http.Response(jsonEncode({'error': code, 'message': message}), status,
        headers: {'content-type': 'application/json'});

/// Gives the test a tall surface.
///
/// Width stays at a realistic 360dp so layout overflow is still caught; only
/// the height is unrealistic, so that a long scrolling screen is fully built
/// and `find` does not report below-the-fold widgets as missing.
void useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 7200); // 360 x 2400 logical
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

/// A desktop-browser-sized surface, for the admin panel.
///
/// Above AdaptiveNavScaffold's 900dp breakpoint, so the side rail is exercised
/// rather than the drawer.
void useDesktopSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1440, 2600);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

/// Pumps a screen with a signed-in session above it.
Future<Session> pumpSignedIn(
  WidgetTester tester,
  FakeApi fake,
  Map<String, dynamic> user,
  Widget child, {
  bool desktop = false,
}) async {
  desktop ? useDesktopSurface(tester) : useTallSurface(tester);
  SharedPreferences.setMockInitialValues({});
  final api = ApiClient(baseUrl: 'http://test.local', httpClient: fake.client);
  api.token = 'test-token';
  final session = Session(api);
  await session.signIn('test-token', user);

  await tester.pumpWidget(
    SessionScope(
      session: session,
      child: MaterialApp(theme: AppTheme.light(), home: child),
    ),
  );
  return session;
}

Future<void> pumpSignedOut(WidgetTester tester, FakeApi fake, Widget child) async {
  useTallSurface(tester);
  SharedPreferences.setMockInitialValues({});
  final api = ApiClient(baseUrl: 'http://test.local', httpClient: fake.client);
  final session = Session(api);
  await tester.pumpWidget(
    SessionScope(
      session: session,
      child: MaterialApp(theme: AppTheme.light(), home: child),
    ),
  );
}

const retailerUser = {
  'id': 'USR-0000003',
  'role': 'RETAILER',
  'name': 'Sharma Mobiles',
  'mobile': '9000000003',
  'retailer_id': 'USR-0000003',
};

const distributorUser = {
  'id': 'USR-0000002',
  'role': 'DISTRIBUTOR',
  'name': 'North Distributor',
  'mobile': '9000000002',
};

const adminUser = {
  'id': 'USR-0000001',
  'role': 'SUPER_ADMIN',
  'name': 'Ashish Enterprises',
  'mobile': '9000000001',
};

const customerUser = {
  'id': 'USR-0000006',
  'role': 'CUSTOMER',
  'name': 'Ramesh Kumar',
  'mobile': '9876543210',
  'customer_id': 'CUS-0000001',
  'retailer_id': 'USR-0000003',
};
