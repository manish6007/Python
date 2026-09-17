import 'package:emi_locker_app/features/admin/admin_audit.dart';
import 'package:emi_locker_app/features/admin/admin_dashboard.dart';
import 'package:emi_locker_app/features/admin/admin_licenses.dart';
import 'package:emi_locker_app/features/admin/admin_network.dart';
import 'package:emi_locker_app/features/admin/admin_settings.dart';
import 'package:emi_locker_app/features/admin/admin_shell.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'helpers.dart';

Map<String, dynamic> get _stats => {
      'customers': 3,
      'retailers': 2,
      'distributors': 1,
      'active_finance': 2,
      'overdue_finance': 0,
      'completed_finance': 0,
      'devices_restricted': 0,
      'collected_paise': 0,
      'outstanding_paise': 3600000,
      'activations_used': 2,
      'activations_available': 497,
    };

Map<String, dynamic> get _network => {
      'distributors': [
        {
          'id': 'USR-0000002',
          'name': 'North Distributor',
          'mobile': '9000000002',
          'role': 'DISTRIBUTOR',
          'parent_id': null,
          'status': 'ACTIVE',
          'created_at': '2026-09-16T04:00:00+00:00',
          'total_quota': 500,
          'used_quota': 150,
          'available_quota': 350,
          'retailers': [
            {
              'id': 'USR-0000003',
              'name': 'Sharma Mobiles',
              'mobile': '9000000003',
              'role': 'RETAILER',
              'parent_id': 'USR-0000002',
              'status': 'ACTIVE',
              'created_at': '2026-09-16T04:00:00+00:00',
              'total_quota': 100,
              'used_quota': 1,
              'available_quota': 99,
            },
          ],
        },
      ],
      'unassigned_retailers': [],
    };

void main() {
  testWidgets('the panel shows a side rail on a desktop-sized window',
      (tester) async {
    final fake = FakeApi({
      'GET /reports/dashboard': (_) => _stats,
      'GET /reports/overdue': (_) => {'rows': []},
      'GET /reports/retailers': (_) => {'rows': []},
    });
    await pumpSignedIn(tester, fake, adminUser, const AdminShell(), desktop: true);
    await tester.pumpAndSettle();

    expect(find.byType(NavigationRail), findsOneWidget);
    expect(find.byType(Drawer), findsNothing);
    expect(find.text('Licences'), findsWidgets);
    expect(find.text('Audit log'), findsWidgets);
  });

  testWidgets('the same panel falls back to a drawer on a narrow window',
      (tester) async {
    final fake = FakeApi({
      'GET /reports/dashboard': (_) => _stats,
      'GET /reports/overdue': (_) => {'rows': []},
      'GET /reports/retailers': (_) => {'rows': []},
    });
    await pumpSignedIn(tester, fake, adminUser, const AdminShell());
    await tester.pumpAndSettle();

    expect(find.byType(NavigationRail), findsNothing);
    expect(find.byIcon(Icons.menu), findsOneWidget);
  });

  testWidgets('dashboard reports the platform totals', (tester) async {
    final fake = FakeApi({
      'GET /reports/dashboard': (_) => _stats,
      'GET /reports/overdue': (_) => {
            'rows': [
              {
                'finance_id': 'FIN-0000001',
                'retailer_id': 'USR-0000003',
                'customer_id': 'CUS-0000001',
                'device_id': 'DEV-0000001',
                'overdue_count': 1,
                'overdue_amount': 200000,
                'oldest_due': '2026-12-10',
                'days_past_due': 10,
              },
            ],
          },
      'GET /reports/retailers': (_) => {'rows': []},
    });
    await pumpSignedIn(tester, fake, adminUser,
        const Scaffold(body: AdminDashboard()), desktop: true);
    await tester.pumpAndSettle();

    expect(find.text('₹36,000'), findsOneWidget);
    expect(find.text('497'), findsOneWidget);
    expect(find.text('FIN-0000001'), findsOneWidget);
    expect(find.text('10'), findsWidgets);
  });

  testWidgets('the network reads as distributors with retailers under them',
      (tester) async {
    final fake = FakeApi({'GET /admin/network': (_) => _network});
    await pumpSignedIn(tester, fake, adminUser,
        const Scaffold(body: AdminNetwork()), desktop: true);
    await tester.pumpAndSettle();

    expect(find.text('North Distributor'), findsOneWidget);
    expect(find.text('Sharma Mobiles'), findsOneWidget);
    expect(find.textContaining('350 of 500 activations free'), findsOneWidget);
    expect(find.text('1 distributor'), findsOneWidget);
  });

  testWidgets('a new retailer must be placed under a distributor', (tester) async {
    final fake = FakeApi({
      'GET /admin/network': (_) => _network,
      'POST /admin/users': (_) => {'user_id': 'USR-0000099', 'role': 'RETAILER'},
    });
    await pumpSignedIn(tester, fake, adminUser,
        const Scaffold(body: AdminNetwork()), desktop: true);
    await tester.pumpAndSettle();

    await tester.tap(find.text('Add account'));
    await tester.pumpAndSettle();

    await tester.enterText(
        find.widgetWithText(TextFormField, 'Business name'), 'New Shop');
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Mobile number'), '9000000012');
    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();

    // No distributor picked, so nothing was sent.
    expect(fake.calls.contains('POST /admin/users'), isFalse);
    expect(find.textContaining('Choose which distributor'), findsOneWidget);
  });

  testWidgets('creating a retailer sends its parent distributor', (tester) async {
    final fake = FakeApi({
      'GET /admin/network': (_) => _network,
      'POST /admin/users': (_) => {'user_id': 'USR-0000099', 'role': 'RETAILER'},
    });
    await pumpSignedIn(tester, fake, adminUser,
        const Scaffold(body: AdminNetwork()), desktop: true);
    await tester.pumpAndSettle();

    await tester.tap(find.text('Add account'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Business name'), 'New Shop');
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Mobile number'), '9000000012');

    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('North Distributor').last);
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();

    final body = fake.bodyFor('POST /admin/users');
    expect(body['role'], 'RETAILER');
    expect(body['name'], 'New Shop');
    expect(body['parent_id'], 'USR-0000002');
  });

  testWidgets('suspending an account demands a reason for the audit log',
      (tester) async {
    final fake = FakeApi({
      'GET /admin/network': (_) => _network,
      'POST /admin/users/USR-0000003/status': (_) =>
          {'user_id': 'USR-0000003', 'status': 'SUSPENDED'},
    });
    await pumpSignedIn(tester, fake, adminUser,
        const Scaffold(body: AdminNetwork()), desktop: true);
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Suspend').last);
    await tester.pumpAndSettle();

    // The confirm button is disabled until a reason is typed.
    final disabled = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Suspend'));
    expect(disabled.onPressed, isNull);

    await tester.enterText(
        find.widgetWithText(TextField, 'Reason'), 'cash reconciliation');
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Suspend'));
    await tester.pumpAndSettle();

    final body = fake.bodyFor('POST /admin/users/USR-0000003/status');
    expect(body['status'], 'SUSPENDED');
    expect(body['reason'], 'cash reconciliation');
  });

  testWidgets('an issued key is shown once, with a warning that it is final',
      (tester) async {
    final fake = FakeApi({
      'GET /admin/plans': (_) => {
            'plans': [
              {
                'id': 'PLN-0000002',
                'name': 'BUSINESS',
                'quota': 100,
                'price_paise': 2500000,
                'validity_days': 365,
                'active': 1,
                'issued': 0,
              },
            ],
          },
      'GET /admin/licenses': (_) => {'licenses': []},
      'POST /admin/licenses/generate': (_) => {
            'license_id': 'LIC-0000002',
            'key': 'ABCDE-FGHIJ-KLMNO-PQRST',
            'key_masked': '*****-*****-*****-PQRST',
            'quota': 100,
            'valid_to': '2027-09-16',
            'status': 'AVAILABLE',
          },
    });
    await pumpSignedIn(tester, fake, adminUser,
        const Scaffold(body: AdminLicences()), desktop: true);
    await tester.pumpAndSettle();

    await tester.tap(find.text('Issue licence'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Issue'));
    await tester.pumpAndSettle();

    expect(find.text('ABCDE-FGHIJ-KLMNO-PQRST'), findsOneWidget);
    expect(find.textContaining('cannot be shown again'), findsOneWidget);
    expect(find.text('Copy key'), findsOneWidget);
  });

  testWidgets('settings show rates in rupees and save them in paise',
      (tester) async {
    final fake = FakeApi({
      'GET /admin/settings': (_) => {
            'settings': {
              'commission.retailer_per_activation_paise': {
                'value': 0,
                'default': 0,
                'description': 'Paid to the retailer for each device it activates',
              },
              'business.name': {
                'value': 'Ashish Enterprises',
                'default': 'Ashish Enterprises',
                'description': 'Shown on receipts and certificates',
              },
            },
          },
      'PUT /admin/settings': (_) => {
            'key': 'commission.retailer_per_activation_paise',
            'value': 15000,
          },
    });
    await pumpSignedIn(tester, fake, adminUser,
        const Scaffold(body: AdminSettings()), desktop: true);
    await tester.pumpAndSettle();

    expect(find.text('₹0'), findsOneWidget);
    expect(find.text('Ashish Enterprises'), findsOneWidget);

    await tester.tap(find.byTooltip('Change').first);
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Amount'), '150');
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();

    // Rupees typed, paise sent.
    final body = fake.bodyFor('PUT /admin/settings');
    expect(body['key'], 'commission.retailer_per_activation_paise');
    expect(body['value'], 15000);
  });

  testWidgets('the audit log is read-only: no edit or delete anywhere',
      (tester) async {
    final fake = FakeApi({
      'GET /admin/audit': (_) => {
            'events': [
              {
                'id': 1,
                'actor_id': 'USR-0000001',
                'actor_role': 'SUPER_ADMIN',
                'actor_name': 'Ashish Enterprises',
                'action': 'settings.change',
                'entity_type': 'setting',
                'entity_id': 'commission.retailer_per_activation_paise',
                'before_json': '{"value": 0}',
                'after_json': '{"value": 15000}',
                'created_at': '2026-09-17T09:00:00+00:00',
              },
            ],
          },
    });
    await pumpSignedIn(tester, fake, adminUser,
        const Scaffold(body: AdminAudit()), desktop: true);
    await tester.pumpAndSettle();

    expect(find.text('settings.change'), findsOneWidget);
    expect(find.text('Ashish Enterprises'), findsOneWidget);
    expect(find.byIcon(Icons.edit_outlined), findsNothing);
    expect(find.byIcon(Icons.delete), findsNothing);
    expect(find.byIcon(Icons.delete_outline), findsNothing);
  });
}
