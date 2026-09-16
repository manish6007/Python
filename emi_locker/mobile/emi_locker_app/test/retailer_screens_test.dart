import 'package:emi_locker_app/features/retailer/collect_screen.dart';
import 'package:emi_locker_app/features/retailer/collections_screen.dart';
import 'package:emi_locker_app/features/retailer/customer_detail_screen.dart';
import 'package:emi_locker_app/features/retailer/new_finance_screen.dart';
import 'package:emi_locker_app/features/retailer/retailer_home.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'helpers.dart';

Map<String, dynamic> _dashboard({int available = 99, int total = 100}) => {
      'retailer_id': 'USR-0000003',
      'customers': 2,
      'active_finance': 1,
      'overdue_finance': 0,
      'completed_finance': 0,
      'outstanding_paise': 2200000,
      'due_today_paise': 0,
      'collected_today_paise': 0,
      'wallet': {
        'owner_id': 'USR-0000003',
        'total': total,
        'used': total - available,
        'reserved': 0,
        'available': available,
      },
    };

Map<String, dynamic> _customer({List<String> missing = const []}) => {
      'id': 'CUS-0000001',
      'retailer_id': 'USR-0000003',
      'name': 'Ramesh Kumar',
      'mobile': '9876543210',
      'address': 'Indore, MP',
      'kyc_status': 'PENDING',
      'required_consents': ['TERMS', 'PRIVACY', 'DEVICE_MANAGEMENT'],
      'missing_consents': missing,
      'finances': [],
    };

void main() {
  testWidgets('dashboard leads with the activation balance', (tester) async {
    final fake = FakeApi({'GET /retailer/dashboard': (_) => _dashboard()});
    await pumpSignedIn(tester, fake, retailerUser,
        const Scaffold(body: RetailerHome()));
    await tester.pumpAndSettle();

    expect(find.text('Activation balance'), findsOneWidget);
    expect(find.text('99'), findsOneWidget);
    expect(find.text('of 100 available'), findsOneWidget);
    expect(find.text('₹22,000'), findsOneWidget);
  });

  testWidgets('dashboard warns before the retailer runs out of activations',
      (tester) async {
    final fake = FakeApi({'GET /retailer/dashboard': (_) => _dashboard(available: 0)});
    await pumpSignedIn(tester, fake, retailerUser,
        const Scaffold(body: RetailerHome()));
    await tester.pumpAndSettle();

    expect(find.textContaining('no activations left'), findsOneWidget);
  });

  testWidgets('new finance is blocked until every consent is recorded',
      (tester) async {
    final fake = FakeApi({
      'GET /retailer/customers/CUS-0000001': (_) =>
          _customer(missing: ['DEVICE_MANAGEMENT']),
    });
    await pumpSignedIn(tester, fake, retailerUser,
        const CustomerDetailScreen(customerId: 'CUS-0000001'));
    await tester.pumpAndSettle();

    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'New finance'),
    );
    expect(button.onPressed, isNull);
    expect(find.textContaining('Record all consents'), findsOneWidget);
  });

  testWidgets('new finance opens once consents are complete', (tester) async {
    final fake = FakeApi({
      'GET /retailer/customers/CUS-0000001': (_) => _customer(),
    });
    await pumpSignedIn(tester, fake, retailerUser,
        const CustomerDetailScreen(customerId: 'CUS-0000001'));
    await tester.pumpAndSettle();

    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'New finance'),
    );
    expect(button.onPressed, isNotNull);
    expect(find.textContaining('Record all consents'), findsNothing);
  });

  testWidgets('a mistyped IMEI is caught before any network call', (tester) async {
    final fake = FakeApi({'POST /finance/quote': (_) => {}});
    await pumpSignedIn(
      tester,
      fake,
      retailerUser,
      const NewFinanceScreen(
          customerId: 'CUS-0000001', customerName: 'Ramesh Kumar'),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
        find.widgetWithText(TextFormField, 'IMEI'), '490154203237519');
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Product price'), '30000');
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Down payment'), '8000');
    await tester.tap(find.text('Calculate EMI'));
    await tester.pumpAndSettle();

    expect(find.textContaining('fails its checksum'), findsOneWidget);
    expect(fake.calls, isEmpty);
  });

  testWidgets('a down payment at or above the price is refused', (tester) async {
    final fake = FakeApi({'POST /finance/quote': (_) => {}});
    await pumpSignedIn(
      tester,
      fake,
      retailerUser,
      const NewFinanceScreen(
          customerId: 'CUS-0000001', customerName: 'Ramesh Kumar'),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
        find.widgetWithText(TextFormField, 'IMEI'), '490154203237518');
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Product price'), '30000');
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Down payment'), '30000');
    await tester.tap(find.text('Calculate EMI'));
    await tester.pumpAndSettle();

    expect(find.textContaining('must be less than the price'), findsOneWidget);
    expect(fake.calls, isEmpty);
  });

  testWidgets('the agreement shows the backend quote, and activation is idempotent',
      (tester) async {
    final fake = FakeApi({
      'POST /finance/quote': (_) => {
            'product_price': 3000000,
            'down_payment': 800000,
            'financed_amount': 2200000,
            'tenure_months': 11,
            'emi_amount': 200000,
            'final_emi_amount': 200000,
            'total_payable': 2200000,
            'first_due_date': '2026-10-10',
            'schedule': [
              for (var i = 1; i <= 11; i++)
                {'seq': i, 'amount_paise': 200000, 'due_date': '2026-10-10'}
            ],
          },
      'POST /finance': (_) => {'finance_id': 'FIN-0000009'},
    });
    await pumpSignedIn(
      tester,
      fake,
      retailerUser,
      const NewFinanceScreen(
          customerId: 'CUS-0000001', customerName: 'Ramesh Kumar'),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
        find.widgetWithText(TextFormField, 'IMEI'), '490154203237518');
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Product price'), '30000');
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Down payment'), '8000');
    await tester.tap(find.text('Calculate EMI'));
    await tester.pumpAndSettle();

    // Figures on the agreement come from the server, not from local maths.
    expect(find.text('Finance terms'), findsOneWidget);
    expect(find.text('₹2,000'), findsWidgets);
    expect(find.text('11 months'), findsOneWidget);

    // Rupees typed by the retailer reached the API as paise.
    expect(fake.bodies.last['product_price'], 3000000);
    expect(fake.bodies.last['down_payment'], 800000);

    await tester.tap(find.text('Customer agrees — activate finance'));
    await tester.pumpAndSettle();

    expect(fake.calls, contains('POST /finance'));
    final key = fake.headers.last['Idempotency-Key'];
    expect(key, isNotNull);
    expect(key!.startsWith('fin-'), isTrue);
  });

  testWidgets('collections shows an honest empty state', (tester) async {
    final fake = FakeApi({
      'GET /retailer/collections/pending': (_) => {'pending': [], 'total_paise': 0},
    });
    await pumpSignedIn(tester, fake, retailerUser,
        const Scaffold(body: CollectionsScreen()));
    await tester.pumpAndSettle();

    expect(find.text('Nothing due'), findsOneWidget);
  });

  testWidgets('collections totals what is owed and lists the worst first',
      (tester) async {
    final fake = FakeApi({
      'GET /retailer/collections/pending': (_) => {
            'total_paise': 400000,
            'pending': [
              {
                'emi_id': 'EMI-3',
                'seq': 3,
                'amount_paise': 200000,
                'due_date': '2026-12-10',
                'status': 'OVERDUE',
                'finance_id': 'FIN-1',
                'customer_id': 'CUS-1',
                'customer_name': 'Ramesh Kumar',
                'mobile': '9876543210',
                'days_past_due': 10,
              },
              {
                'emi_id': 'EMI-4',
                'seq': 4,
                'amount_paise': 200000,
                'due_date': '2027-01-10',
                'status': 'DUE',
                'finance_id': 'FIN-1',
                'customer_id': 'CUS-1',
                'customer_name': 'Sunita Devi',
                'mobile': '9876543211',
                'days_past_due': 0,
              },
            ],
          },
    });
    await pumpSignedIn(tester, fake, retailerUser,
        const Scaffold(body: CollectionsScreen()));
    await tester.pumpAndSettle();

    expect(find.text('₹4,000'), findsOneWidget);
    expect(find.textContaining('10d late'), findsOneWidget);
    expect(find.text('Overdue'), findsOneWidget);
  });

  testWidgets('a cash collection sends the exact instalment and a retry key',
      (tester) async {
    final fake = FakeApi({
      'POST /collections': (_) => {'payment_id': 'PAY-5', 'receipt_number': 'AE/1'},
      'GET /receipts/PAY-5': (_) => {
            'receipt_number': 'AE/2026/000002',
            'issued_at': '2026-10-10T10:30:00+00:00',
            'amount_paise': 200000,
            'method': 'CASH',
            'finance_id': 'FIN-1',
            'emi_seq': 2,
            'customer_name': 'Ramesh Kumar',
            'customer_mobile': '9876543210',
            'retailer_name': 'Sharma Mobiles',
          },
    });
    await pumpSignedIn(
      tester,
      fake,
      retailerUser,
      const CollectScreen(
        financeId: 'FIN-1',
        emiId: 'EMI-2',
        seq: 2,
        amountPaise: 200000,
        customerName: 'Ramesh Kumar',
        mobile: '9876543210',
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Confirm collection'));
    await tester.pumpAndSettle();

    final body = fake.bodies.first;
    expect(body['amount_paise'], 200000);
    expect(body['emi_id'], 'EMI-2');
    expect(body['mode'], 'CASH');
    expect(fake.headers.first['Idempotency-Key']!.startsWith('cash-'), isTrue);

    expect(find.text('Payment received'), findsOneWidget);
    expect(find.text('AE/2026/000002'), findsOneWidget);
  });
}
