import 'package:emi_locker_app/features/distributor/commission_screen.dart';
import 'package:emi_locker_app/features/distributor/distributor_home.dart';
import 'package:emi_locker_app/features/distributor/retailer_detail_screen.dart';
import 'package:emi_locker_app/features/distributor/retailers_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'helpers.dart';

Map<String, dynamic> _dashboard({int available = 350}) => {
      'distributor_id': 'USR-0000002',
      'retailers': 2,
      'customers': 3,
      'active_finance': 2,
      'overdue_finance': 0,
      'outstanding_paise': 3600000,
      'wallet': {
        'owner_id': 'USR-0000002',
        'total': 500,
        'used': 500 - available,
        'reserved': 0,
        'available': available,
      },
      'allocated_to_retailers': 150,
      'activations_used_downstream': 2,
    };

void main() {
  testWidgets('dashboard leads with stock and shows the network total',
      (tester) async {
    final fake = FakeApi({'GET /distributor/dashboard': (_) => _dashboard()});
    await pumpSignedIn(tester, fake, distributorUser,
        const Scaffold(body: DistributorHome()));
    await tester.pumpAndSettle();

    expect(find.text('Activation stock'), findsOneWidget);
    expect(find.text('350'), findsOneWidget);
    expect(find.text('of 500 left to allocate'), findsOneWidget);
    expect(find.text('₹36,000'), findsOneWidget);
    // Allocated 150, used 2 downstream, so 148 are still sitting with retailers.
    expect(find.text('148'), findsOneWidget);
  });

  testWidgets('a distributor with no stock left is shown as zero', (tester) async {
    final fake = FakeApi({
      'GET /distributor/dashboard': (_) => _dashboard(available: 0),
    });
    await pumpSignedIn(tester, fake, distributorUser,
        const Scaffold(body: DistributorHome()));
    await tester.pumpAndSettle();

    expect(find.text('0'), findsWidgets);
    expect(find.text('of 500 left to allocate'), findsOneWidget);
  });

  testWidgets('retailers list shows stock and money per retailer', (tester) async {
    final fake = FakeApi({
      'GET /distributor/retailers': (_) => {
            'retailers': [
              {
                'id': 'USR-0000003',
                'name': 'Sharma Mobiles',
                'mobile': '9000000003',
                'status': 'ACTIVE',
                'created_at': '2026-09-16T04:00:00+00:00',
                'total_quota': 100,
                'used_quota': 1,
                'available_quota': 99,
                'customers': 2,
                'active_finance': 1,
                'overdue_finance': 0,
                'outstanding_paise': 2200000,
              },
            ],
          },
    });
    await pumpSignedIn(tester, fake, distributorUser,
        const Scaffold(body: RetailersScreen()));
    await tester.pumpAndSettle();

    expect(find.text('Sharma Mobiles'), findsOneWidget);
    expect(find.text('99'), findsOneWidget);
    expect(find.text('₹22,000'), findsOneWidget);
  });

  testWidgets('a distributor with no retailers is told why the list is empty',
      (tester) async {
    final fake = FakeApi({'GET /distributor/retailers': (_) => {'retailers': []}});
    await pumpSignedIn(tester, fake, distributorUser,
        const Scaffold(body: RetailersScreen()));
    await tester.pumpAndSettle();

    expect(find.text('No retailers yet'), findsOneWidget);
  });

  testWidgets('allocating sends the amount once, with a retry key',
      (tester) async {
    final fake = FakeApi({
      'GET /distributor/retailers/USR-0000003': (_) => {
            'retailer': {
              'id': 'USR-0000003',
              'name': 'Sharma Mobiles',
              'mobile': '9000000003',
              'status': 'ACTIVE',
              'created_at': '2026-09-16T04:00:00+00:00',
            },
            'wallet': {
              'owner_id': 'USR-0000003',
              'total': 100,
              'used': 1,
              'reserved': 0,
              'available': 99,
            },
            'finances': [],
            'allocations': [],
          },
      'POST /distributor/allocate': (_) => {
            'allocation_id': 'ALC-0000003',
            'to_owner': 'USR-0000003',
            'quota': 25,
            'wallet': {
              'owner_id': 'USR-0000003',
              'total': 125,
              'used': 1,
              'reserved': 0,
              'available': 124,
            },
          },
    });
    await pumpSignedIn(
      tester,
      fake,
      distributorUser,
      const RetailerDetailScreen(
          retailerId: 'USR-0000003', retailerName: 'Sharma Mobiles'),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Allocate activations'));
    await tester.pumpAndSettle();

    expect(find.text('Allocate to Sharma Mobiles'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Allocate'));
    await tester.pumpAndSettle();

    expect(fake.countOf('POST /distributor/allocate'), 1);
    final body = fake.bodyFor('POST /distributor/allocate');
    expect(body['to_owner'], 'USR-0000003');
    expect(body['quota'], 25);
    final key = fake.headersFor('POST /distributor/allocate')['Idempotency-Key'];
    expect(key, isNotNull);
    expect(key!.startsWith('alloc-'), isTrue);
  });

  testWidgets('a rejected allocation shows the backend reason and stays open',
      (tester) async {
    final fake = FakeApi({
      'GET /distributor/retailers/USR-0000003': (_) => {
            'retailer': {
              'id': 'USR-0000003',
              'name': 'Sharma Mobiles',
              'mobile': '9000000003',
              'status': 'ACTIVE',
              'created_at': '2026-09-16T04:00:00+00:00',
            },
            'wallet': {
              'owner_id': 'USR-0000003',
              'total': 100,
              'used': 1,
              'reserved': 0,
              'available': 99,
            },
            'finances': [],
            'allocations': [],
          },
      'POST /distributor/allocate': (_) => errorResponse(409, 'INSUFFICIENT_QUOTA',
          'distributor USR-0000002 has 10 activations available, needs 25'),
    });
    await pumpSignedIn(
      tester,
      fake,
      distributorUser,
      const RetailerDetailScreen(
          retailerId: 'USR-0000003', retailerName: 'Sharma Mobiles'),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Allocate activations'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Allocate'));
    await tester.pumpAndSettle();

    expect(find.textContaining('has 10 activations available'), findsOneWidget);
    expect(find.text('Allocate to Sharma Mobiles'), findsOneWidget);
  });

  testWidgets('commission says nothing is configured rather than showing zero',
      (tester) async {
    final fake = FakeApi({
      'GET /distributor/commission': (_) => {
            'rules': {
              'distributor_per_activation_paise': 0,
              'retailer_per_activation_paise': 0,
              'distributor_percent_of_financed_bp': 0,
              'configured': false,
            },
            'rows': [
              {
                'owner_id': 'USR-0000003',
                'name': 'Sharma Mobiles',
                'role': 'RETAILER',
                'activations': 1,
                'financed_paise': 2200000,
                'commission_paise': 0,
              },
            ],
            'total_paise': 0,
          },
    });
    await pumpSignedIn(tester, fake, distributorUser,
        const Scaffold(body: CommissionScreen()));
    await tester.pumpAndSettle();

    expect(find.textContaining('No commission rate has been set yet'), findsOneWidget);
    expect(find.text('Earned across the network'), findsNothing);
  });

  testWidgets('commission shows earnings once a rate exists', (tester) async {
    final fake = FakeApi({
      'GET /distributor/commission': (_) => {
            'rules': {
              'distributor_per_activation_paise': 0,
              'retailer_per_activation_paise': 15000,
              'distributor_percent_of_financed_bp': 250,
              'configured': true,
            },
            'rows': [
              {
                'owner_id': 'USR-0000003',
                'name': 'Sharma Mobiles',
                'role': 'RETAILER',
                'activations': 2,
                'financed_paise': 2200000,
                'commission_paise': 30000,
              },
            ],
            'total_paise': 30000,
          },
    });
    await pumpSignedIn(tester, fake, distributorUser,
        const Scaffold(body: CommissionScreen()));
    await tester.pumpAndSettle();

    expect(find.text('Earned across the network'), findsOneWidget);
    expect(find.text('₹300'), findsWidgets);
    expect(find.text('2.5%'), findsOneWidget);
  });
}
