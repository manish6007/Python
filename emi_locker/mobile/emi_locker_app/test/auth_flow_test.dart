import 'package:emi_locker_app/features/auth/login_screen.dart';
import 'package:emi_locker_app/features/auth/otp_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'helpers.dart';

void main() {
  testWidgets('a short mobile number never reaches the network', (tester) async {
    final fake = FakeApi({'POST /auth/send-otp': (_) => {'sent': true}});
    await pumpSignedOut(tester, fake, const LoginScreen());
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextFormField), '98765');
    await tester.tap(find.text('Send OTP'));
    await tester.pumpAndSettle();

    expect(find.text('Enter a 10-digit mobile number'), findsOneWidget);
    expect(fake.calls, isEmpty);
  });

  testWidgets('sending an OTP moves to the verify screen', (tester) async {
    final fake = FakeApi({
      'POST /auth/send-otp': (_) => {'sent': true, 'mobile': '9000000003'},
    });
    await pumpSignedOut(tester, fake, const LoginScreen());
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextFormField), '9000000003');
    await tester.tap(find.text('Send OTP'));
    await tester.pumpAndSettle();

    expect(fake.bodies.single['mobile'], '9000000003');
    expect(find.text('Enter the code'), findsOneWidget);
    expect(find.textContaining('+91 9000000003'), findsOneWidget);
  });

  testWidgets('a local backend prefills the code and says why', (tester) async {
    final fake = FakeApi({});
    await pumpSignedOut(
      tester,
      fake,
      const OtpScreen(mobile: '9000000003', devOtp: '123456'),
    );
    await tester.pumpAndSettle();

    expect(find.text('123456'), findsOneWidget);
    expect(find.textContaining('Local test mode'), findsOneWidget);
  });

  testWidgets('a production backend sends no code, and none is shown',
      (tester) async {
    final fake = FakeApi({});
    await pumpSignedOut(tester, fake, const OtpScreen(mobile: '9000000003'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Local test mode'), findsNothing);
  });

  testWidgets('a wrong code shows the backend reason and stays put',
      (tester) async {
    final fake = FakeApi({
      'POST /auth/verify-otp': (_) =>
          errorResponse(403, 'PERMISSION_DENIED', 'incorrect code'),
    });
    await pumpSignedOut(
      tester,
      fake,
      const OtpScreen(mobile: '9000000003', devOtp: '111111'),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Verify and sign in'));
    await tester.pumpAndSettle();

    expect(find.text('incorrect code'), findsOneWidget);
    expect(find.text('Verify and sign in'), findsOneWidget);
  });

  testWidgets('resend is locked out until the cooldown expires', (tester) async {
    final fake = FakeApi({});
    await pumpSignedOut(
      tester,
      fake,
      const OtpScreen(mobile: '9000000003', devOtp: '111111'),
    );
    await tester.pump();

    expect(find.textContaining('Resend code in'), findsOneWidget);
    final button = tester.widget<TextButton>(find.byType(TextButton));
    expect(button.onPressed, isNull);

    await tester.pump(const Duration(seconds: 31));
    expect(find.text('Resend code'), findsOneWidget);
  });
}
