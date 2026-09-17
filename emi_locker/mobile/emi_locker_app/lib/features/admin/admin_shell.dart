import 'package:flutter/material.dart';

import '../../core/adaptive.dart';
import '../../main.dart';
import 'admin_audit.dart';
import 'admin_dashboard.dart';
import 'admin_devices.dart';
import 'admin_finances.dart';
import 'admin_licenses.dart';
import 'admin_network.dart';
import 'admin_payments.dart';
import 'admin_people.dart';
import 'admin_settings.dart';

/// The Super Admin panel.
///
/// Built for a desktop browser (`flutter run -d chrome`) but it is the same
/// Flutter code as the apps, so it also runs on a tablet or phone - the
/// navigation adapts at 900dp.
class AdminShell extends StatelessWidget {
  const AdminShell({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AdaptiveNavScaffold(
      title: 'EMI Locker',
      subtitle: session.displayName,
      actions: [
        IconButton(
          tooltip: 'Sign out',
          onPressed: session.signOut,
          icon: const Icon(Icons.logout),
        ),
        const SizedBox(width: 8),
      ],
      items: const [
        NavItem('Dashboard', Icons.dashboard_outlined, _dashboard),
        NavItem('Network', Icons.account_tree_outlined, _network),
        NavItem('Customers', Icons.people_outline, _customers),
        NavItem('Finance', Icons.request_quote_outlined, _finances),
        NavItem('Devices', Icons.smartphone_outlined, _devices),
        NavItem('Payments', Icons.payments_outlined, _payments),
        NavItem('Licences', Icons.key_outlined, _licences),
        NavItem('Settings', Icons.settings_outlined, _settings),
        NavItem('Audit log', Icons.history_outlined, _audit),
      ],
    );
  }
}

Widget _dashboard(BuildContext _) => const AdminDashboard();
Widget _network(BuildContext _) => const AdminNetwork();
Widget _customers(BuildContext _) => const AdminPeople();
Widget _finances(BuildContext _) => const AdminFinances();
Widget _devices(BuildContext _) => const AdminDevices();
Widget _payments(BuildContext _) => const AdminPayments();
Widget _licences(BuildContext _) => const AdminLicences();
Widget _settings(BuildContext _) => const AdminSettings();
Widget _audit(BuildContext _) => const AdminAudit();
