import 'package:emi_locker_app/features/customer/customer_home.dart';
import 'package:emi_locker_app/features/customer/pay_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'helpers.dart';

Map<String, dynamic> _finance({
  int outstanding = 2200000,
  String status = 'ACTIVE',
  String deviceStatus = 'ACTIVE',
}) =>
    {
      'finance_id': 'FIN-0000001',
      'status': status,
      'principal': 2200000,
      'emi_amount': 200000,
      'tenure_months': 11,
      'start_date': '2026-09-10',
      'imei': '490154203237518',
      'model': 'Galaxy A16',
      'device_status': deviceStatus,
      'outstanding_paise': outstanding,
      'paid_count': (2200000 - outstanding) ~/ 200000,
      'next_due': {
        'id': 'EMI-0000001',
        'seq': 1,
        'amount_paise': 200000,
        'due_date': '2026-10-10',
        'status': 'UPCOMING',
      },
    };

void main() {
  testWidgets('shows the outstanding amount and next instalment', (tester) async {
    final fake = FakeApi({
      'GET /me/finances': (_) => {
            'customer_id': 'CUS-0000001',
            'finances': [_finance()],
          },
    });
    await pumpSignedIn(tester, fake, customerUser,
        const Scaffold(body: CustomerHome()));
    await tester.pumpAndSettle();

    expect(find.text('Galaxy A16'), findsOneWidget);
    expect(find.text('₹22,000'), findsOneWidget);
    expect(find.textContaining('0 of 11 instalments paid'), findsOneWidget);
    expect(find.textContaining('EMI 1 due 10 Oct 2026'), findsOneWidget);
  });

  testWidgets('tells a new customer why the screen is empty', (tester) async {
    final fake = FakeApi({
      'GET /me/finances': (_) => {'customer_id': 'CUS-2', 'finances': []},
    });
    await pumpSignedIn(tester, fake, customerUser,
        const Scaffold(body: CustomerHome()));
    await tester.pumpAndSettle();

    expect(find.text('No EMI plan yet'), findsOneWidget);
  });

  testWidgets('warns when the device has been restricted', (tester) async {
    final fake = FakeApi({
      'GET /me/finances': (_) => {
            'customer_id': 'CUS-0000001',
            'finances': [_finance(deviceStatus: 'RESTRICTED', status: 'OVERDUE')],
          },
    });
    await pumpSignedIn(tester, fake, customerUser,
        const Scaffold(body: CustomerHome()));
    await tester.pumpAndSettle();

    expect(find.textContaining('This device is restricted'), findsOneWidget);
    expect(find.textContaining('Clearing the arrears restores it'), findsOneWidget);
  });

  testWidgets('surfaces a backend failure with a retry instead of a blank screen',
      (tester) async {
    final fake = FakeApi({
      'GET /me/finances': (_) =>
          errorResponse(500, 'SERVER', 'The server is having a bad day'),
    });
    await pumpSignedIn(tester, fake, customerUser,
        const Scaffold(body: CustomerHome()));
    await tester.pumpAndSettle();

    expect(find.text('The server is having a bad day'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });

  testWidgets(
      'paying never tells the backend the payment worked - it asks the gateway',
      (tester) async {
    final fake = FakeApi({
      'POST /payments/create': (_) =>
          {'payment_id': 'PAY-0000001', 'emi_id': 'EMI-0000001',
           'amount_paise': 200000, 'status': 'INITIATED'},
      'POST /mock-gateway/pay': (_) => {
            'payment_id': 'PAY-0000001',
            'status': 'SUCCESS',
            'receipt_number': 'AE/2026/000001',
          },
      'GET /receipts/PAY-0000001': (_) => {
            'receipt_number': 'AE/2026/000001',
            'issued_at': '2026-10-10T10:30:00+00:00',
            'amount_paise': 200000,
            'method': 'ONLINE',
            'finance_id': 'FIN-0000001',
            'emi_seq': 1,
            'customer_name': 'Ramesh Kumar',
            'customer_mobile': '9876543210',
            'retailer_name': 'Sharma Mobiles',
          },
    });

    await pumpSignedIn(
      tester,
      fake,
      customerUser,
      const PayScreen(
        financeId: 'FIN-0000001',
        emiId: 'EMI-0000001',
        seq: 1,
        amountPaise: 200000,
        dueDate: '2026-10-10',
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('₹2,000'), findsOneWidget);
    await tester.tap(find.text('Pay now'));
    await tester.pumpAndSettle();

    // The order matters: create, then hand off, then read the verified result.
    expect(fake.calls, [
      'POST /payments/create',
      'POST /mock-gateway/pay',
      'GET /receipts/PAY-0000001',
    ]);
    // Nothing the app sent claims success - it only asked for one.
    expect(fake.bodies[0].containsKey('status'), isFalse);

    expect(find.text('Payment received'), findsOneWidget);
    expect(find.text('AE/2026/000001'), findsOneWidget);
  });

  testWidgets('a declined payment is reported, and no receipt is shown',
      (tester) async {
    final fake = FakeApi({
      'POST /payments/create': (_) =>
          {'payment_id': 'PAY-2', 'emi_id': 'EMI-1', 'amount_paise': 200000},
      'POST /mock-gateway/pay': (_) => {'payment_id': 'PAY-2', 'status': 'FAILED'},
    });

    await pumpSignedIn(
      tester,
      fake,
      customerUser,
      const PayScreen(
        financeId: 'FIN-0000001',
        emiId: 'EMI-0000001',
        seq: 1,
        amountPaise: 200000,
        dueDate: '2026-10-10',
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Pay now'));
    await tester.pumpAndSettle();

    expect(find.textContaining('did not go through'), findsOneWidget);
    expect(find.text('Payment received'), findsNothing);
    expect(find.text('Pay now'), findsOneWidget);
  });
}
