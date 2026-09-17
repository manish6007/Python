import 'package:flutter/material.dart';

import '../../main.dart';
import 'commission_screen.dart';
import 'distributor_home.dart';
import 'licenses_screen.dart';
import 'retailers_screen.dart';

class DistributorShell extends StatefulWidget {
  const DistributorShell({super.key});

  @override
  State<DistributorShell> createState() => _DistributorShellState();
}

class _DistributorShellState extends State<DistributorShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(session.displayName, style: const TextStyle(fontSize: 18)),
            Text(
              'Distributor',
              style: TextStyle(
                fontSize: 12,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            onPressed: session.signOut,
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: IndexedStack(
        index: _index,
        children: const [
          DistributorHome(),
          RetailersScreen(),
          LicensesScreen(),
          CommissionScreen(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(
              icon: Icon(Icons.dashboard_outlined),
              selectedIcon: Icon(Icons.dashboard),
              label: 'Dashboard'),
          NavigationDestination(
              icon: Icon(Icons.storefront_outlined),
              selectedIcon: Icon(Icons.storefront),
              label: 'Retailers'),
          NavigationDestination(
              icon: Icon(Icons.key_outlined),
              selectedIcon: Icon(Icons.key),
              label: 'Licences'),
          NavigationDestination(
              icon: Icon(Icons.percent_outlined),
              selectedIcon: Icon(Icons.percent),
              label: 'Commission'),
        ],
      ),
    );
  }
}
